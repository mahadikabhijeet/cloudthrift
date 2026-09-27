#!/usr/bin/env python3
"""
CloudThrift AWS-spend estimation agent.

Turns a thin prospect profile (headcount + workload class) into a defensible,
range-based estimate of monthly AWS spend, likely waste (savings), a conservative
audit guarantee figure, and workload-specific "intelligent findings" — the stuff
we can lead the outreach with instead of a generic number.

Model (heuristic, transparent):
  monthly_bill  ~=  headcount  x  $/employee/month  (by workload class)
  savings       ~=  monthly_bill x waste%           (FinOps industry waste band)
  guarantee     =   conservative round-down of the LOW savings estimate

It's an ESTIMATE for targeting + framing, never stated to the prospect as their
real bill. Enriches crm/pipeline-state.json in place.

Run:  python3 pillar-a/outreach/scripts/estimate_spend.py
"""
import json, math, pathlib

STATE = pathlib.Path(__file__).resolve().parents[3] / "crm" / "pipeline-state.json"

# $/employee/month AWS spend band + waste band + likely findings, by workload class.
WORKLOAD = {
    "lean": {
        "per": (150, 350), "waste": (0.20, 0.30),
        "findings": [
            "Idle / oversized EC2 with no Savings Plan or RI coverage",
            "Unattached EBS volumes and forgotten snapshots",
            "gp2 volumes not migrated to gp3 (~20% cheaper, same performance)",
            "Idle Elastic IPs and load balancers left running",
        ],
    },
    "standard": {
        "per": (200, 450), "waste": (0.22, 0.32),
        "findings": [
            "Idle load balancers and unattached EBS from fast iteration",
            "No Savings Plans / RI coverage on steady-state compute",
            "Over-provisioned RDS instances running 24/7",
            "NAT Gateway egress and cross-AZ data-transfer creep",
        ],
    },
    "data_heavy": {
        "per": (350, 700), "waste": (0.25, 0.35),
        "findings": [
            "S3 with no lifecycle/tiering — cold data billed at hot-tier rates",
            "Orphaned EBS/RDS snapshots accumulating for months",
            "Over-provisioned RDS/OpenSearch sized for peak, idle off-peak",
            "Cross-AZ replication and egress data-transfer charges",
        ],
    },
    "compute_heavy": {
        "per": (500, 1000), "waste": (0.25, 0.38),
        "findings": [
            "Idle or oversized GPU / accelerated instances between jobs",
            "On-demand pricing where Savings Plans or Spot would fit",
            "Dev / staging GPU fleets running 24/7",
            "No autoscaling on inference endpoints",
        ],
    },
    "compliance": {
        "per": (250, 500), "waste": (0.25, 0.35),
        "findings": [
            "Redundant multi-AZ / DR infra sized for peak, idle most of the time",
            "Backups and snapshots with no retention policy",
            "Instances over-provisioned 'just in case' for compliance headroom",
            "Duplicate logging / audit storage never tiered",
        ],
    },
}

# Per-prospect profile + open-source email intel (headcount from recon; workload from product).
PROFILES = {
    "truein":     {"headcount": 80,  "workload": "standard",
                   "email": "atanna@truein.com", "email_confidence": 95,
                   "email_evidence": "Used in the first send (2026-07-20), no bounce — confirmed deliverable."},
    "promobi":    {"headcount": 254, "workload": "lean",
                   "email": "arnab@scalefusion.com", "email_confidence": 40,
                   "email_evidence": "No public address or scraped pattern found. scalefusion.com likely first@; promobitech.com also possible. Low confidence."},
    "rocketlane": {"headcount": 303, "workload": "standard",
                   "email": "sri@rocketlane.com", "email_confidence": 70,
                   "email_evidence": "ContactOut scrape surfaced sri@rocketlane.com (short first-name alias, common for founders). Unconfirmed."},
    "facilio":    {"headcount": 246, "workload": "data_heavy",
                   "email": "yogendrababu@facilio.com", "email_confidence": 72,
                   "email_evidence": "Pattern data: 72.7% of facilio.com use first@ format. Full name confirmed via LinkedIn."},
    "webengage":  {"headcount": 412, "workload": "data_heavy",
                   "email": "avlesh.singh@webengage.com", "email_confidence": 67,
                   "email_evidence": "Pattern data: 66.9% of webengage.com use first.last@ format. Name confirmed."},
    "pazcare":    {"headcount": 200, "workload": "compliance",
                   "email": "sanchit.malik@pazcare.com", "email_confidence": 72,
                   "email_evidence": "Pattern data: 72.4% of pazcare.com use first.last@ format. Name confirmed."},
    "leena-ai":   {"headcount": 271, "workload": "compute_heavy",
                   "email": "anand@leena.ai", "email_confidence": 45,
                   "email_evidence": "No scraped pattern found. Short domain — first@ common for founders/CTOs. Unconfirmed, low-medium."},
    # --- International (US / EMEA), from prior session recon (9dda3720), 2026-07-21 ---
    "metronome":  {"headcount": 158, "workload": "data_heavy",
                   "email": "chan@metronome.com", "email_confidence": 85,
                   "email_evidence": "LeadIQ: first@metronome.com used 88% (PATTERN-HIGH). Chan Chandrapunth confirmed on LinkedIn."},
    "treasury-prime": {"headcount": 57, "workload": "standard",
                   "email": "carlos@treasuryprime.com", "email_confidence": 78,
                   "email_evidence": "LeadIQ/RocketReach: first@treasuryprime.com used 79.5% (PATTERN-HIGH). Carlos Armas, VP Eng, on team page."},
    "highnote":   {"headcount": 161, "workload": "compliance",
                   "email": "", "email_confidence": 30,
                   "email_evidence": "Aggregators split between highnote.com and highnoteplatform.com — ambiguous. DO NOT send until the real domain is confirmed."},
    "qdrant":     {"headcount": 146, "workload": "data_heavy",
                   "email": "fabrizio.schmidt@qdrant.tech", "email_confidence": 68,
                   "email_evidence": "LeadIQ: first.last@qdrant.tech used 67.3% (mail domain is qdrant.tech, NOT .io). PATTERN-HIGH."},
    "protex-ai":  {"headcount": 75, "workload": "compute_heavy",
                   "email": "ciaran.omara@protex.ai", "email_confidence": 87,
                   "email_evidence": "RocketReach: first.last@protex.ai used 88% (PATTERN-HIGH). Ciarán O'Mara, Co-Founder & CTO."},
    "griffin":    {"headcount": 140, "workload": "compliance",
                   "email": "james@griffin.sh", "email_confidence": 74,
                   "email_evidence": "LeadIQ: first@griffin.sh used 73% — mail domain is griffin.sh, NOT griffin.com (would bounce). PATTERN-HIGH."},
    # --- added 2026-07-27. All three are GIT-VERIFIED DIRECTLY OBSERVED (the 2/2-delivered
    # class), so the SETTLED guard below will keep these addresses; the entries exist only to
    # feed the spend model. Headcounts are ESTIMATES for sizing, never quoted to a prospect.
    "axiom":      {"headcount": 40, "workload": "data_heavy",
                   "email": "seif@axiom.co", "email_confidence": 95,
                   "email_evidence": "GIT DIRECTLY OBSERVED: 87 commits by seif@axiom.co (axiomhq). Co-Founder & CTO."},
    "zilliz":     {"headcount": 180, "workload": "data_heavy",
                   "email": "zhenshan.cao@zilliz.com", "email_confidence": 90,
                   "email_evidence": "GIT DIRECTLY OBSERVED: 4 commits by zhenshan.cao@zilliz.com (zilliztech); org pattern first.last@, 19 addresses, no exception."},
    # Parked (GCP control plane, see lead notes) but kept profiled so its draft carries a
    # real guarantee figure rather than an invented one, if it is ever revisited.
    "weaviate":   {"headcount": 120, "workload": "data_heavy",
                   "email": "", "email_confidence": 0,
                   "email_evidence": "Parked off-target. etienne@dilocker.de was directly observed in commits."},
    "tigerdata":  {"headcount": 170, "workload": "data_heavy",
                   "email": "sven@tigerdata.com", "email_confidence": 90,
                   "email_evidence": "GIT DIRECTLY OBSERVED: 66 commits by sven@tigerdata.com (timescale). Company runs timescale.com AND tigerdata.com; both MX live."},
    # --- added 2026-07-28. All six GIT-VERIFIED DIRECTLY OBSERVED; entries feed the spend
    # model only. Headcounts are ESTIMATES for sizing, never quoted to a prospect.
    "sfcompute":  {"headcount": 30,  "workload": "compute_heavy", "email": "evan@sfcompute.com", "email_confidence": 92, "email_evidence": "GIT DIRECTLY OBSERVED. Co-Founder & CEO."},
    "modal":      {"headcount": 135, "workload": "compute_heavy", "email": "charles@modal.com", "email_confidence": 88, "email_evidence": "GIT DIRECTLY OBSERVED, 66 commits."},
    "depot":      {"headcount": 52,  "workload": "compute_heavy", "email": "rob@depot.dev", "email_confidence": 88, "email_evidence": "GIT DIRECTLY OBSERVED."},
    "cartesia":   {"headcount": 50,  "workload": "compute_heavy", "email": "grant.timmerman@cartesia.ai", "email_confidence": 88, "email_evidence": "GIT DIRECTLY OBSERVED, 24 commits."},
    "motherduck": {"headcount": 110, "workload": "data_heavy",    "email": "guen@motherduck.com", "email_confidence": 88, "email_evidence": "GIT DIRECTLY OBSERVED, 70 commits."},
    "marqo":      {"headcount": 40,  "workload": "data_heavy",    "email": "li@marqo.ai", "email_confidence": 85, "email_evidence": "GIT DIRECTLY OBSERVED, 61 commits."},
}


def r1k(x):   # round to nearest $1,000
    return int(round(x / 1000.0)) * 1000

def floor5k(x):   # round DOWN to nearest $5,000 (conservative)
    return int(math.floor(x / 5000.0)) * 5000

def estimate(headcount, workload):
    w = WORKLOAD[workload]
    bill_low, bill_high = r1k(headcount * w["per"][0]), r1k(headcount * w["per"][1])
    sav_low = r1k(bill_low * w["waste"][0])
    sav_high = r1k(bill_high * w["waste"][1])
    guarantee = max(5000, floor5k(sav_low))   # never promise above the low estimate
    return {
        "workload_class": workload,
        "est_bill_low": bill_low, "est_bill_high": bill_high,
        "est_savings_low": sav_low, "est_savings_high": sav_high,
        "guarantee_usd": guarantee,
        "findings": w["findings"],
    }


def main():
    state = json.loads(STATE.read_text())
    for lead in state["leads"]:
        p = PROFILES.get(lead["id"])
        if not p:
            continue
        est = estimate(p["headcount"], p["workload"])
        lead.update(est)
        lead["headcount"] = p["headcount"]
        # NEVER downgrade an address that real evidence has already settled. PROFILES
        # holds the original scraper guesses (~40% accurate); git-verification and live
        # delivery outrank them. Without this guard, re-running the estimator silently
        # reverted allen@griffin.sh / andrey@vasnetsov.com to the addresses that bounced.
        SETTLED = {"delivered", "verified-in-use", "pattern-confirmed", "unverified-blocked",
           "parked-off-target", "zb-valid"}   # 2026-07-27: parked/ZeroBounce-proven
                                              # statuses were being reset to "guessed"
        if lead.get("email_status") in SETTLED:
            print(f"  [keep] {lead['id']}: email {lead.get('email')!r} "
                  f"({lead['email_status']}) — not overwritten by PROFILES")
        else:
            lead["email"] = p["email"]
            lead["email_confidence"] = p["email_confidence"]
            lead["email_evidence"] = p["email_evidence"]
            lead["email_status"] = "known-good" if p["email_confidence"] >= 90 else "guessed"
        # Tailor the draft's guarantee figure (replace the generic "20k" with $Nk).
        gk = est["guarantee_usd"] // 1000
        if lead.get("draft_body"):
            lead["draft_body"] = lead["draft_body"].replace("20k", f"${gk}k")
        print(f"{lead['company']:<22} bill ${est['est_bill_low']//1000}k-${est['est_bill_high']//1000}k/mo | "
              f"savings ${est['est_savings_low']//1000}k-${est['est_savings_high']//1000}k | "
              f"guarantee ${gk}k | email {lead.get('email_confidence','?')}% "
              f"({lead.get('email_status','?')})")
    STATE.write_text(json.dumps(state, indent=2))
    print(f"\nEnriched {len(state['leads'])} leads -> {STATE}")


if __name__ == "__main__":
    main()
