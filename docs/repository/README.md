# Repository Maintenance

- [Structure audit and remaining code-refactoring work](structure_audit_20261009.md)
- [Document migration and verification](document_migration_20261009.md)
- [G+R C++ extraction and equivalence evidence](grasu_component_refactor/README.md)
- [SST/Spine extraction, regression matrix, and existing failures](sst_spine_refactor/README.md)
- [Old-to-new document paths](document_locations.json)
- [Detailed record catalog](document_catalog.md)

The catalog is a lookup appendix, not the documentation's reading order.
For ordinary reading start at the [documentation index](../README.md).

## Checks

Run from the repository root:

```bash
python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
python3 -m unittest discover -s tests -p 'test_repository_structure.py'
```

The structure check covers the document layout and migration map. Frozen
figure-input/output identity checks are separate:

```bash
python3 -m unittest discover -s tests -p 'test_figure7_10_handoff.py'
```

Neither check runs a graph campaign, measures hardware, or recalibrates a model.
