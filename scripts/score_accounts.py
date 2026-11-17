"""Score every active account for churn risk and expansion likelihood from usage signals.

Training data is fct_account_features_monthly: point-in-time features at each monthly snapshot,
with labels from the 3 months that follow. Validation is out-of-time: models train on snapshots
up to Jan 2026 and are scored on snapshots from Apr to Aug 2026, which they never saw.

Labels
  churn_or_major_contraction  next 3 months of revenue below 25% of the last 3 months
  expansion                   next 3 months of revenue at least 1.4x the last 3 months

Logistic regression is the production model because each score can be explained to a rep
(the feature pushing the score up the most is written as the reason). A gradient-boosted
model is trained alongside it as a check on how much accuracy that choice gives up.

Outputs
  ml.account_scores                 one row per active account, scored as of the end of actuals
  ml.scoring_validation             out-of-time metrics per label and model
  exports/account_scores_for_crm.csv  CRM-ready file (Salesforce-style custom field names)
"""
from __future__ import annotations

import os

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(ROOT, "target", "usage_revenue.duckdb")
TRAIN_END = pd.Timestamp("2026-01-01")
TEST_START, TEST_END = pd.Timestamp("2026-04-01"), pd.Timestamp("2026-08-01")
SCORE_DATE = pd.Timestamp("2026-11-01")
LABELS = {"churn": "label_churn_or_major_contraction", "expansion": "label_expansion"}

FEATURE_NAMES = {
    "log_rev_l3m": "revenue size (last 3 months)",
    "growth_l3m_vs_p3m": "revenue growth vs prior 3 months",
    "growth_l1m_vs_l2m": "revenue change last month",
    "has_commit": "has a commit contract",
    "commit_utilization_l1m": "usage as a share of commit",
    "active_days_share_l30d": "share of last 30 days with traffic",
    "gpu_types_l3m": "GPU types in use",
    "gpu_types_added_l2m": "new GPU type added recently",
    "deployments_l60d": "model deployments, last 60 days",
    "deployment_change": "change in deployments vs prior 60 days",
    "days_since_last_deployment": "days since last deployment",
    "tenure_months": "months as a customer",
    "seg_enterprise": "Enterprise segment",
    "seg_startup": "Startup segment",
}


def features(df: pd.DataFrame) -> pd.DataFrame:
    x = pd.DataFrame(index=df.index)
    x["log_rev_l3m"] = np.log1p(df.rev_l3m)
    x["growth_l3m_vs_p3m"] = df.growth_l3m_vs_p3m.fillna(1).clip(0, 5)
    x["growth_l1m_vs_l2m"] = df.growth_l1m_vs_l2m.fillna(1).clip(0, 5)
    x["has_commit"] = df.has_commit.astype(float)
    x["commit_utilization_l1m"] = df.commit_utilization_l1m.fillna(0).clip(0, 5)
    x["active_days_share_l30d"] = df.active_days_l30d / 30
    x["gpu_types_l3m"] = df.gpu_types_l3m
    x["gpu_types_added_l2m"] = df.gpu_types_added_l2m
    x["deployments_l60d"] = df.deployments_l60d
    x["deployment_change"] = df.deployments_l60d - df.deployments_p60d
    x["days_since_last_deployment"] = df.days_since_last_deployment.clip(upper=365)
    x["tenure_months"] = df.tenure_months
    x["seg_enterprise"] = (df.segment == "Enterprise").astype(float)
    x["seg_startup"] = (df.segment == "Startup").astype(float)
    return x


def top_decile_capture(y, s):
    k = max(1, int(round(len(s) * 0.10)))
    top = np.argsort(-s)[:k]
    return y[top].sum() / max(y.sum(), 1)


def reason(model, xrow: pd.Series) -> str:
    scaler, lr = model.named_steps["standardscaler"], model.named_steps["logisticregression"]
    z = (xrow.values - scaler.mean_) / scaler.scale_
    contrib = z * lr.coef_[0]
    return FEATURE_NAMES[xrow.index[int(np.argmax(contrib))]]


def main():
    con = duckdb.connect(DB)
    df = con.sql("select * from fct_account_features_monthly").df()
    df["snapshot_date"] = pd.to_datetime(df.snapshot_date)
    x_all = features(df)

    train = df.label_observed & (df.snapshot_date <= TRAIN_END)
    test = df.label_observed & df.snapshot_date.between(TEST_START, TEST_END)
    now = df.snapshot_date == SCORE_DATE

    metrics, models = [], {}
    for name, col in LABELS.items():
        y = df[col].astype(float)
        lr = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000, C=0.5))
        gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, random_state=0)
        for mname, m in [("logistic_regression", lr), ("gradient_boosting", gb)]:
            m.fit(x_all[train], y[train])
            s = m.predict_proba(x_all[test])[:, 1]
            yt = y[test].values
            metrics.append({
                "label": name, "model": mname,
                "train_rows": int(train.sum()), "test_rows": int(test.sum()),
                "test_positives": int(yt.sum()), "test_base_rate": yt.mean(),
                "roc_auc": roc_auc_score(yt, s), "average_precision": average_precision_score(yt, s),
                "top_decile_capture": top_decile_capture(yt, s),
            })
        models[name] = lr

    met = pd.DataFrame(metrics)
    print("Out-of-time validation (train: snapshots to Jan 2026; test: Apr-Aug 2026 snapshots)")
    print(met.round(3).to_string(index=False))

    cur = df[now].copy()
    xc = x_all[now]
    out = cur[["account_id", "segment", "rev_l3m"]].copy()
    for name, m in models.items():
        s = m.predict_proba(xc)[:, 1]
        out[f"{name}_score"] = s
        pct = pd.Series(s, index=out.index).rank(pct=True)
        out[f"{name}_tier"] = np.select([pct > 0.9, pct > 0.7], ["Top 10%", "Next 20%"], "Rest")
        out[f"{name}_top_reason"] = [reason(m, xc.loc[i]) for i in xc.index]
    out["scored_as_of"] = SCORE_DATE.date()

    con.sql("create schema if not exists ml")
    con.register("scores_df", out)
    con.register("met_df", met)
    con.sql("create or replace table ml.account_scores as select * from scores_df")
    con.sql("create or replace table ml.scoring_validation as select * from met_df")

    os.makedirs(os.path.join(ROOT, "exports"), exist_ok=True)
    crm = out.rename(columns={
        "account_id": "Account_External_Id__c",
        "churn_score": "Churn_Risk_Score__c", "churn_tier": "Churn_Risk_Tier__c",
        "churn_top_reason": "Churn_Risk_Reason__c",
        "expansion_score": "Expansion_Score__c", "expansion_tier": "Expansion_Tier__c",
        "expansion_top_reason": "Expansion_Reason__c", "scored_as_of": "Scores_As_Of__c",
    }).drop(columns=["segment", "rev_l3m"])
    crm = crm.sort_values("Account_External_Id__c")
    crm.round(4).to_csv(os.path.join(ROOT, "exports", "account_scores_for_crm.csv"), index=False)
    print(f"\nScored {len(out)} active accounts as of {SCORE_DATE.date()}; "
          f"top 10% = {(out.churn_tier == 'Top 10%').sum()} accounts per score.")


if __name__ == "__main__":
    main()
