import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import model_evidence as me

HEADER = ("run_date,sector,model_type,decision,reason,old_accuracy,new_accuracy,old_macro_f1,new_macro_f1,"
          "baseline_class,baseline_accuracy,baseline_macro_f1,old_buy_recall,new_buy_recall,old_sell_recall,"
          "new_sell_recall,old_nonhold_share,new_nonhold_share,holdout_rows,holdout_start\n")


def _row(sector, decision, old_acc, new_acc, old_nh, new_nh, base=0.60, run="2026-10-17", rows=1000):
    return (f"{run},{sector},lstm,{decision},r,{old_acc},{new_acc},0.30,0.31,Hold,{base},0.25,0,0,0,0,"
            f"{old_nh},{new_nh},{rows},2026-07-16\n")


def _ev(**kw):
    ev = dict(accuracy=0.60, macro_f1=0.3, nonhold_share=0.2, baseline_accuracy=0.60,
              baseline_macro_f1=0.25, holdout_rows=1000, holdout_start="2026-07-16", run_date="2026-10-17")
    ev.update(kw)
    return ev


def test_model_that_always_says_hold_has_no_edge():
    a = me.assess(_ev(nonhold_share=0.0))
    assert a["level"] == "no_edge" and a["label"] == "No edge"
    assert "Hold 100.0% of the time" in a["caveat"] and "1,000 test samples since 2026-07-16" in a["caveat"]


def test_nonhold_share_threshold_is_five_percent():
    assert me.assess(_ev(nonhold_share=0.049))["level"] == "no_edge"
    assert me.assess(_ev(nonhold_share=0.05))["level"] == "unproven"


def test_active_model_that_does_not_beat_always_hold_is_unproven():
    a = me.assess(_ev(accuracy=0.5, baseline_accuracy=0.6, nonhold_share=0.4))
    assert a["level"] == "unproven"
    assert "50%" in a["caveat"] and "60%" in a["caveat"]


def test_a_clear_accuracy_win_is_tested_but_caveated():
    a = me.assess(_ev(accuracy=0.66, baseline_accuracy=0.60, nonhold_share=0.3))
    assert a["level"] == "tested" and "not proof" in a["caveat"]
    # +1 point is within the margin, so it is not claimed as an edge
    assert me.assess(_ev(accuracy=0.61, baseline_accuracy=0.60, nonhold_share=0.3))["level"] == "unproven"


def test_missing_evidence_is_reported_as_unverified():
    a = me.assess(None)
    assert a["level"] == "unknown" and a["evidence"] is None


def test_loader_uses_new_scores_only_when_candidate_was_promoted(tmp_path):
    p = tmp_path / "retrain_report.csv"
    p.write_text(HEADER
                 + _row("Kept", "kept_current", 0.70, 0.40, 0.30, 0.50)
                 + _row("Promoted", "promoted", 0.40, 0.70, 0.50, 0.30))
    data = me.load_evidence(p)
    assert data["Kept"]["accuracy"] == 0.70 and data["Kept"]["nonhold_share"] == 0.30
    assert data["Promoted"]["accuracy"] == 0.70 and data["Promoted"]["nonhold_share"] == 0.30


def test_loader_takes_the_latest_run_per_sector(tmp_path):
    p = tmp_path / "retrain_report.csv"
    p.write_text(HEADER + _row("A", "kept_current", 0.55, 0.55, 0.2, 0.2, run="2026-10-10")
                 + _row("A", "kept_current", 0.65, 0.65, 0.2, 0.2, run="2026-10-17"))
    assert me.load_evidence(p)["A"]["accuracy"] == 0.65


def test_missing_file_or_unknown_sector_gives_no_evidence(tmp_path):
    assert me.load_evidence(tmp_path / "nope.csv") == {}
    p = tmp_path / "retrain_report.csv"
    p.write_text(HEADER + _row("A", "kept_current", 0.6, 0.6, 0.2, 0.2))
    assert me.for_sector("Nonexistent", p) is None
    assert me.assess(me.for_sector("Nonexistent", p))["level"] == "unknown"


def test_deployed_report_gives_a_verdict_for_every_sector():
    """The shipped report must cover all 12 sectors and never crash the verdict."""
    data = me.load_evidence(Path("deploy_data/models/retrain_report.csv"))
    assert len(data) == 12
    assert {me.assess(ev)["level"] for ev in data.values()} <= {"no_edge", "unproven", "tested"}
