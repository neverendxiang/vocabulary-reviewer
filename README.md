# Vocabulary Reviewer

A local quiz app for `organized_vocabulary_notes.xlsx`.

## Run

```powershell
python server.py
```

Open:

```text
http://127.0.0.1:8000
```

To use the app on a phone, keep the computer and phone on the same Wi-Fi network, leave the server running, and open `http://<computer-LAN-IP>:8000` on the phone. The server listens on the local network by default. Windows Firewall may ask you to allow Python on private networks.

## Ubuntu Service

After cloning the project on an Ubuntu server, run the installer from the project folder:

```bash
sudo bash ./install_vcb_rver.sh
```

It registers and starts a `systemd` service named `vcb_rver`, using the cloned folder as the app directory. The service starts automatically after reboot.

Useful commands:

```bash
sudo systemctl status vcb_rver
journalctl -u vcb_rver -f
sudo systemctl restart vcb_rver
```

Service settings are stored in:

```text
/etc/default/vcb_rver
```

Edit that file to change `VOCAB_PORT`, `VOCAB_HOST`, or the Ubuntu paths to your Oxford/Longman `.mdx` dictionaries. Then restart:

```bash
sudo systemctl restart vcb_rver
```

## Notes

- The app reads vocabulary rows from workbook sheets that have the vocabulary headers.
- Sheets with `Review` or `Summary` in their name are skipped.
- Definition questions are deduplicated by canonical English word, so repeated workbook rows and translation variants do not create duplicate questions.
- Multiple-choice questions have 5 total choices, including the correct answer.
- English definitions are read from the local Oxford MDX dictionary at `C:\Users\eason\Desktop\package\oxford\牛津9英英(推荐)\Oxford ALD_9th_En-En.mdx`.
- The local MDX index is cached in `oxford_mdx_index.json` after the first lookup. You can override the dictionary path with `LOCAL_OXFORD_MDX`.
- If Oxford has no entry, the app tries Longman dictionaries from `C:\Users\eason\Desktop\package\longmang`: LDOCE6 first, then Longman Phrasal Verbs. Their indexes are cached as `longman_mdx_index.json` and `longman_phrasal_mdx_index.json`.
- If the local Oxford and Longman dictionaries have no entry, the app searches FreeDictionaryAPI.com (structured Wiktionary data) and then Free Dictionary API. Successful responses are cached in `definitions_cache.json`.
- If all definition sources miss, the quiz reveals the original workbook word and lets the user continue.
- If the local MDX file is missing or has no entry for a word, the app can also use Oxford Dictionaries API.
- Set `OXFORD_APP_ID` and `OXFORD_APP_KEY` before starting the server. Optional: set `OXFORD_LANGUAGE`, which defaults to `en-us`.
- The quiz prompt does not use the workbook's Chinese meaning as a definition. If Oxford is not configured or cannot find an entry, the app shows an Oxford-unavailable message and lets you move on.
- Wrong answers are appended to `wrong_answers.json`.
- Quiz progress is permanently autosaved to `progress.json`, including the queue order, current position, mode, and session stats. Writes are atomic, the previous state is retained in `progress.backup.json`, and the browser sends a final save when the page closes. Questions follow workbook order. Use the in-app reset button to clear both progress files and start over.
- After answering a multiple-choice question, click any choice chip to view that word's dictionary definition and optionally reveal its example sentence. Press Enter to advance to the next question; clicking empty page space does not advance.
- Each definition question has an optional **Show example sentence** button. Examples use the same Oxford-first, Longman-fallback order as definitions.
- Multiple-choice answers are numbered 1-5 and can be selected with the corresponding number key.
- After selecting a multiple-choice answer, use **Undo choice** to reverse the attempt and choose again. Session stats, progress, and saved wrong answers are corrected automatically.
- No separate dictionary file is required, but Oxford lookups need internet access and Oxford API credentials.

PowerShell example:

```powershell
$env:OXFORD_APP_ID="your_app_id"
$env:OXFORD_APP_KEY="your_app_key"
python server.py
```
