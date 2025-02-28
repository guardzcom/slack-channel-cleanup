# Slack Channel Cleanup

A Python script to manage Slack channels in bulk, supporting operations like renaming, archiving, and merging channels. Perfect for workspace cleanup and reorganization.

## Features

- 🔍 Export all channels (public and private) to CSV
- 📝 Review and plan changes in your spreadsheet app
- 🔄 Bulk actions: rename, archive, or merge channels
- ✨ Interactive approval process with detailed channel info
- 🛡️ Safe execution with dry-run mode and backups
- 📊 Real-time progress and summary reporting

## Prerequisites

- Python 3.6+
- A Slack user token (xoxp) with the following scopes:
  - `channels:read` - For listing public channels
  - `groups:read` - For listing private channels
  - `channels:write` - For managing public channels
  - `groups:write` - For managing private channels
  - `chat:write` - For posting messages (used for merge notifications)

## Quick Start

1. Clone and install:
```bash
git clone https://github.com/yourusername/slack-channel-cleanup.git
cd slack-channel-cleanup
pip install -r requirements.txt
```

2. Create a `.env` file with your Slack token:
```bash
SLACK_TOKEN=xoxp-your-token-here
```

3. Export channels to CSV:
```bash
python -m src.channel_renamer export -f channels.csv
```

4. Edit the CSV file and set actions:
- `keep` - No changes (default)
- `archive` - Archive the channel
- `merge` - Merge into another channel (set target in `target_value`)
- `rename` - Rename channel (set new name in `target_value`)

5. Test your changes (dry run):
```bash
python -m src.channel_renamer execute -f channels.csv --dry-run
```

6. Execute changes:
```bash
python -m src.channel_renamer execute -f channels.csv
```

## Command Line Options

```bash
python -m src.channel_renamer <mode> [options]

Modes:
  export                Export channels to CSV
  execute               Execute actions from CSV

Options:
  -f, --file FILE      CSV file path (required)
  -y, --yes            Skip initial confirmation
  -d, --dry-run        Simulate execution without making changes
```

## Safety Features

- ✅ Interactive approval for each action
- ⚠️ Extra confirmation for destructive actions
- 🔍 Dry run mode to preview changes
- 💾 Automatic CSV backups
- 🔒 Permission and name validation
- 📝 Detailed logging and error reporting

## Limitations

- Cannot archive:
  - The general/default channel
  - Required channels
  - Channels where you're not a member
- Cannot rename:
  - Archived channels
  - Channels without proper permissions
  - To names that already exist
- Channel names must be:
  - Lowercase
  - No spaces or periods
  - Max 80 characters
  - Only letters, numbers, hyphens, underscores

## Debugging

- Use VSCode's debug configurations (included in `.vscode/launch.json`)
- Check the Slack API responses for detailed error messages
- Use `--dry-run` to validate changes before executing
- Review CSV backups (`*.bak`) if needed

## License

MIT License - Feel free to use and modify as needed.

## Security Note

- Never commit your `.env` file
- Keep your Slack token secure
- Review changes carefully before execution
- Consider running `--dry-run` first 