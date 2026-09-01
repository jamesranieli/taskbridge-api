# Unit Test Cases

The assessment test suite is located in `tests/test_assessment.py`.

| Test | Purpose |
|---|---|
| Equal notification dispatch | Verifies that all supplied project team members receive a notification on a project state change. |
| Audit entry on milestone update | Verifies that a milestone state change creates the required audit entry. |
| Audit immutability | Verifies that audit entries cannot be deleted or overwritten. |
| Audit date-range filter | Verifies that audit history can be filtered by date range. |
| Audit event-type filter | Verifies that audit history can be filtered by event type. |
| Cross-organisation access | Verifies that an unauthorised user cannot access another organisation's audit history. |

Run the tests with:

`pytest tests/test_assessment.py -v`

The final assessment run completed with all six tests passing.
