# xauto Examples

### `example.py`
A minimal example demonstrating:
- Config loading and freezing
- Firefox anti detection options loading
- Task manager and driver pool setup
- Loading multiple URLs in parallel

### `mullvad_cleaner.py`
Automates:
- Logging into a Mullvad account using an environment variable
- Revoking devices while keeping known ones
- Uses direct driver access instead of the task manager

> Make sure to export your Mullvad token before running:
> ```bash
> export MULLVAD_ACCOUNT="9876543210"
> ```

---

Try run examples with:

```bash
python examples/example.py
python examples/mullvad_cleaner.py
