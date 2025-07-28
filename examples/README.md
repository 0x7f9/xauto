# xauto Examples

### `example.py`
A minimal example demonstrating:
- Config loading and freezing
- Firefox anti detection options loading
- Task manager and driver pool setup
- Loading multiple URLs in parallel

### `exploitdb_scraper.py`
Automates scraping Exploit-DB:
- Waits for page load with JS API injection
- Detects bot/challenge pages before trying to parse
- Parses exploit list and details with lxml
- Saves extracted comments and metadata to markdown

### `mullvad_cleaner.py`
Automates clearing devices:
- Waits for page load with JS API injection
- Detects bot/challenge pages before trying to parse
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
python examples/exploitdb_scraper.py 
python examples/mullvad_cleaner.py
