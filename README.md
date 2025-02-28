# Slack Channel Manager

A Python script to manage Slack channels in bulk, supporting operations like renaming, archiving, and merging channels. Perfect for workspace cleanup and reorganization.

> 🤖 Built with [Cursor](https://cursor.sh/), the AI-first code editor, and its Claude-powered assistant.

## ⚠️ Warning

This tool performs bulk operations that can permanently affect your Slack workspace. While it includes safety features, you are responsible for any changes made to your channels. Please use thoughtfully!

## Why?

Managing Slack channels at scale can be tedious and error-prone. This tool helps you:
- Clean up inactive channels
- Reorganize channel naming
- Merge redundant channels
- Review changes before executing
- Keep audit trail of all actions

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

To get a Slack token:
1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create a new app in your workspace
3. Add the required scopes under "OAuth & Permissions"
4. Install the app to your workspace
5. Copy the "User OAuth Token" (starts with `xoxp-`)

## Setup

Create a `.env` file with your Slack token:
```bash
SLACK_TOKEN=xoxp-your-token-here
```

## Usage

1. Export channels to CSV:
```bash
python -m src.channel_renamer export -f channels.csv
```

This will create a CSV file with columns:
```csv
channel_id,name,is_private,member_count,created_date,action,target_value,notes
C12345678,general,false,50,2022-01-01,keep,,
C87654321,team-dev,true,10,2023-03-15,merge,team-engineering,Moving to unified team channel
C98765432,old-project,false,5,2022-06-20,archive,,Inactive since 2023
```

2. Edit the CSV file and set actions:
- `keep` - No changes (default)
- `archive` - Archive the channel
- `merge` - Merge into another channel (set target in `target_value`)
- `rename` - Rename channel (set new name in `target_value`)

3. Test your changes (dry run):
```bash
python -m src.channel_renamer execute -f channels.csv --dry-run
```

4. Execute changes:
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

## Contributing

Contributions are welcome! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests

## Credits

- Built with [Cursor](https://cursor.sh/) and its Claude-powered AI assistant
- Special thanks to the Slack API community

## License

MIT License - Feel free to use and modify as needed.

## Security Note

- Never commit your `.env` file
- Keep your Slack token secure
- Review changes carefully before execution
- Consider running `--dry-run` first 