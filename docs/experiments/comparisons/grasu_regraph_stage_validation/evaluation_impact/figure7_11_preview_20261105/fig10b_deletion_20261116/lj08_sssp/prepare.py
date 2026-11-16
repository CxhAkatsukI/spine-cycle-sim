import csv
import hashlib
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent
PUBLIC = Path("/data/tmp/spine-lj08-sssp-u512-deletion-batches-20261116")
FROZEN = Path("/data/chuxiao/fig7-respr-propagation-fig10b-20261116.cnPau7QX/fig10b-lj08-sssp-frozen")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ensure(ok, reason):
    if not ok:
        raise ValueError(reason)


def main():
    with (PUBLIC / "manifest.tsv").open() as stream:
        rows = {int(row["deletion_pct"]): row for row in csv.DictReader(stream, delimiter="\t")}
    order = (50, 100, 25, 75, 0)
    ensure(set(rows) == set(order), "unexpected percentages in frozen manifest")
    base_hash = digest(FROZEN / "base.bin")
    before_hash = digest(FROZEN / "oracle.before")
    for pct in order:
        row = rows[pct]
        batch = PUBLIC / row["file"]
        ensure(base_hash == row["base_bin_sha256"], "base graph hash mismatch")
        ensure(before_hash == row["oracle_before_sha256"], "initial oracle hash mismatch")
        ensure(digest(batch) == row["batch_sha256"], f"batch hash mismatch: {pct}%")
        output = ROOT / "cases" / f"delete{pct:03d}"
        output.mkdir(parents=True, exist_ok=True)
        translated = []
        deletes = 0
        for line in batch.read_text().splitlines():
            op, src, dst, weight = line.split()
            ensure(op in {"+", "-"}, f"unknown update {op}")
            deletes += op == "-"
            translated.append(f"{src} {dst} {weight} {-1 if op == '-' else 1}\n")
        ensure(len(translated) == 512 and deletes * 100 == pct * 512, f"wrong update counts: {pct}%")
        (output / "batch.slice").write_text("".join(translated))

        after = output / "oracle.after"
        if not after.exists() or digest(after) != row["oracle_after_sha256"]:
            if pct == 50:
                shutil.copyfile(FROZEN / "delete050.7g3tHMeG" / "oracle.after", after)
            else:
                with (output / "oracle.log").open("w") as log:
                    subprocess.run(
                        [FROZEN / "board-reference", "sssp-overlay", FROZEN / "base.bin", batch,
                         "5363260", "99028542", after, "26"],
                        stdout=log, stderr=subprocess.STDOUT, check=True,
                    )
        ensure(digest(after) == row["oracle_after_sha256"], f"oracle mismatch: {pct}%")
        (output / "ready").touch()
        print(f"OK {pct}%: {deletes} deletes, {512 - deletes} inserts, CPU oracle matches", flush=True)


if __name__ == "__main__":
    main()
