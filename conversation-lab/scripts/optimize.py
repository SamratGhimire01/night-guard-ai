"""First real DSPy optimization run: MIPROv2 (light) over the production reply-style rules, seed set = lab/seed_set.py,
metric = the calibrated judge (default reasoning effort, 3 samples). Saves the program + trial log under results/."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dspy

from lab.llm import configure
from lab.programs import RulesReceptionist, make_metric, to_example
from lab.seed_set import TRAIN, VAL

smoke = "--smoke" in sys.argv
lm = configure()  # default reasoning effort, pinned
metric = make_metric(samples=3)
student = RulesReceptionist()
train, val = [to_example(i) for i in TRAIN], [to_example(i) for i in VAL]

if smoke:  # time + sanity-check the unoptimized program + metric on 3 val items
    for ex in val[:3]:
        t = time.time()
        pred = student(**{k: ex[k] for k in ex.inputs()})
        t1 = time.time() - t
        s = metric(ex, pred)
        print(f"{ex.customer_message!r:40} -> {pred.response[:70]!r}  metric {s:.2f}  (reply {t1:.1f}s, +judge {time.time() - t - t1:.1f}s)")
    sys.exit()

out = Path(__file__).resolve().parents[1] / "results" / f"optimize_{time.strftime('%Y%m%d_%H%M%S')}"
out.mkdir(parents=True)
base_val = dspy.Evaluate(devset=val, metric=metric, num_threads=4, display_progress=False)(student).score
print(f"unoptimized (production rules, no demos) val score: {base_val:.1f}", flush=True)

opt = dspy.MIPROv2(metric=metric, prompt_model=lm, task_model=lm, auto="light", num_threads=4, seed=0,
                   max_bootstrapped_demos=3, max_labeled_demos=0, metric_threshold=0.9, verbose=True, track_stats=True,
                   log_dir=str(out / "mipro_log"))
t0 = time.time()
best = opt.compile(student, trainset=train, valset=val, requires_permission_to_run=False)
print(f"\nMIPROv2 compile finished in {(time.time() - t0) / 60:.1f} min", flush=True)
best.save(str(out / "optimized_program.json"))
(out / "optimized_instruction.txt").write_text(best.reply.signature.instructions)
ev = dspy.Evaluate(devset=val, metric=metric, num_threads=4, display_progress=False)
REPEATS = 3  # winner's-curse guard: re-score the returned program AND the start program several times before believing any number
start_re = [ev(student).score for _ in range(REPEATS)]
opt_re = [ev(best).score for _ in range(REPEATS)]
from statistics import mean, pstdev
trials = {str(k): {kk: (vv if isinstance(vv, (int, float, str, list, dict, bool, type(None))) else str(vv))
                   for kk, vv in v.items()} for k, v in getattr(best, "trial_logs", {}).items()}
stats = {"unoptimized_val_first": base_val, "start_program_rescores": start_re, "optimized_program_rescores": opt_re,
         "n_train": len(train), "n_val": len(val), "demos": len(best.reply.demos),
         "instruction_unchanged": best.reply.signature.instructions == student.reply.signature.instructions,
         "compile_minutes": round((time.time() - t0) / 60, 1), "trial_logs": trials}
(out / "run_stats.json").write_text(json.dumps(stats, indent=1, default=str))
scores = [(k, v.get("full_eval_score") or v.get("score")) for k, v in trials.items()]
print("trial full-eval scores:", [(k, round(x, 1)) for k, x in scores if x is not None])
print(f"START program val re-scores x{REPEATS}: {[round(x, 1) for x in start_re]}  mean {mean(start_re):.1f} sd {pstdev(start_re):.1f}")
print(f"OPTIMIZED program val re-scores x{REPEATS}: {[round(x, 1) for x in opt_re]}  mean {mean(opt_re):.1f} sd {pstdev(opt_re):.1f}")
print(f"instruction unchanged: {stats['instruction_unchanged']}; demos: {stats['demos']}")
print("(val is what MIPRO selected on; NOT a held-out number)")
print("saved", out)
