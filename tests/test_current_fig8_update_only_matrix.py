from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.run_current_fig8_update_only_matrix import (
    build_tasks,
    case_directory,
    publish_views,
)


class CurrentFig8UpdateOnlyMatrixTests(unittest.TestCase):
    def test_matrix_deduplicates_au_cross_and_batch_case(self) -> None:
        tasks = build_tasks(("au", "su"), 512, (64, 512, 4096))

        self.assertEqual(len(tasks), 4)
        self.assertEqual(
            sum(key == "au" and updates == 512 for key, _, _, updates in tasks),
            1,
        )

    def test_published_views_share_the_same_au_512_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for key, updates in (("au", 64), ("au", 512), ("au", 4096), ("su", 512)):
                case_directory(root, key, updates).mkdir(parents=True)

            publish_views(root, ("au", "su"), 512, (64, 512, 4096))

            self.assertEqual(
                (root / "cross_dataset" / "au").resolve(),
                case_directory(root, "au", 512).resolve(),
            )
            self.assertEqual(
                (root / "batch_sensitivity" / "b512").resolve(),
                case_directory(root, "au", 512).resolve(),
            )
            self.assertEqual(
                (root / "cross_dataset" / "su").resolve(),
                case_directory(root, "su", 512).resolve(),
            )


if __name__ == "__main__":
    unittest.main()
