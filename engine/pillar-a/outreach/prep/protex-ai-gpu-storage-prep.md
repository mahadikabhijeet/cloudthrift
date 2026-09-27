# Prep — Protex AI (GPU + storage FinOps talking points)

For the call **if Ciarán O'Mara (Co-Founder & CTO) replies.** They're seasoned + it's a
computer-vision workload, so lead with questions, not claims. You're a fresh read-only
pair of eyes, not there to teach them their infra.

## What Protex's AWS bill is probably made of
Computer-vision / CCTV safety AI = two big cost centres:
1. **GPU compute** — model inference on video streams (steady, 24/7) + periodic training/retraining (bursty).
2. **Storage + data transfer** — lots of video/frames landing in S3, plus egress moving it around.

## GPU cost drivers (where the waste hides)
- **On-demand vs commitment.** Steady inference on on-demand GPU is the #1 leak. A 1-year
  **Compute Savings Plan** is ~up to 60% off vs on-demand for a baseline they always run.
- **Training on on-demand instead of Spot.** Interruptible training/batch jobs on **Spot**
  can be 60–90% cheaper. Big lever if they retrain often.
- **Idle GPU between jobs** and **dev/staging GPU left running 24/7** — classic zombie spend.
- **Over-provisioned GPU family** — e.g. running p4/p5 where g5/g6 inference GPUs would do,
  or full GPUs where **inference could batch** or use smaller accelerators (Inferentia).
- **No autoscaling on the inference fleet** — provisioned for peak, idle off-peak.

## Storage / data-transfer cost drivers
- **S3 with no lifecycle/tiering** — old footage sitting in S3 Standard at hot-tier price.
  **Intelligent-Tiering** or lifecycle to IA/Glacier for cold video is often a big, safe win.
- **Orphaned EBS snapshots** and **gp2 volumes not moved to gp3** (~20% cheaper, same perf).
- **Cross-AZ / cross-region + egress** — moving video around is expensive; VPC endpoints and
  keeping processing in-region cut this.

## Smart questions to ask (make you sound credible, not salesy)
- "Is your steady inference on on-demand, or have you put Savings Plans / Spot under it?"
- "Roughly what GPU utilisation are you seeing on the inference fleet?"
- "How's video retention set up — lifecycle to Glacier, or mostly S3 Standard?"
- "Training/retraining — how often, and is that on Spot?"
- "Any autoscaling on inference, or provisioned for peak?"

## Quick wins to name (only if they engage)
Savings Plans on baseline inference · Spot for training · S3 Intelligent-Tiering/lifecycle
for cold footage · gp3 migration · right-size / scheduled-shutdown of dev GPUs ·
VPC endpoints to cut egress. **The audit quantifies which of these actually apply.**

## Framing if they push ("we already watch this")
"Totally, and you probably do more than most. The audit is read-only and takes an afternoon
of access, worst case you get a clean bill of health, best case I find a Savings-Plan or
tiering gap that pays for itself. Happy to just send the 1-page checklist first."
