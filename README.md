# Slack Channel Curator

A Python script to thoughtfully curate Slack channels, supporting operations like renaming and archiving channels. Perfect for workspace cleanup and reorganization.

> 🤖 Built with [Cursor](https://cursor.sh/), the AI-first code editor, and its Claude-powered assistant.

## ⚠️ Warning

This tool performs bulk operations that can permanently affect your Slack workspace. While it includes safety features, you are responsible for any changes made to your channels. Please use thoughtfully!

## Why?

Managing Slack channels at scale can be tedious and error-prone. This tool helps you:
- Clean up inactive channels
- Reorganize channel naming
- Consolidate redundant channels
- Review changes before executing
- Keep audit trail of all actions

## Features

- 🔍 Maintains a spreadsheet of all channels (public and private)
- 📝 Review and plan changes in your preferred format (CSV or Google Sheets)
- 🔄 Bulk actions: rename or archive channels (with optional redirect notices)
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
  - `chat:write` - For posting redirect notices (optional)

Note: Admin privileges are recommended for full workspace management capabilities.

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

## Google Sheets Integration

To use Google Sheets as your spreadsheet format:

1. Set up Google Cloud Project:
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Create a new project or select an existing one
   - Enable the Google Sheets API for your project

2. Create Service Account:
   - Go to "IAM & Admin" > "Service Accounts"
   - Click "Create Service Account"
   - Name it (e.g., "slack-channel-curator")
   - Click "Create and Continue"
   - Skip role assignment
   - Click "Done"

3. Download Credentials:
   - Click on the newly created service account
   - Go to "Keys" tab
   - Click "Add Key" > "Create new key"
   - Choose JSON format
   - Save the downloaded file as `service-account.json` in your project directory

4. Share your Google Sheet:
   - Create a new Google Sheet
   - Click "Share" in the top right
   - Add the service account email (found in `service-account.json`) with "Editor" access
   - Copy the sheet URL

5. Run the script with the `--sheet` option:
```bash
python slack_channel_curator.py --sheet "YOUR-SHEET-URL"
```

The sheet will be automatically populated with your channels and kept in sync.

## Usage

The script maintains a spreadsheet of all your Slack channels. Each time you run it, it will:
1. Process any pending actions from the spreadsheet
2. Update the channel list with any new channels
3. Keep the spreadsheet in sync with your workspace

Choose your preferred format:
```bash
# Using CSV format
python slack_channel_curator.py -f channels.csv

# Using Google Sheets
python slack_channel_curator.py --sheet "YOUR-SHEET-URL"

# Test changes with dry run mode
python slack_channel_curator.py -f channels.csv --dry-run
```

The spreadsheet has the following columns:
- channel_id: Slack's internal channel ID
- name: Channel name
- is_private: Whether the channel is private
- member_count: Number of members
- created_date: When the channel was created
- action: What action to take (keep, archive, rename)
- target_value: Target for rename or archive redirect
- notes: Optional notes about the change

To make changes:
1. Edit the spreadsheet and set actions:
   - `keep` - No changes (default)
   - `archive` - Archive the channel. Optionally specify a target channel in `target_value` to post a redirect notice
   - `rename` - Rename channel (set new name in `target_value`)
2. Run the script again to process your changes
3. The script will:
   - Show you each proposed change
   - Ask for confirmation
   - Execute approved changes
   - Update the spreadsheet to reflect the changes

## Command Line Options

```bash
python slack_channel_curator.py [options]

Options:
  -f, --file FILE      Path to CSV file (cannot be used with --sheet)
  --sheet URL          Google Sheets URL (cannot be used with --file)
  -d, --dry-run        Simulate execution without making changes

Note: You must specify either --file OR --sheet, but not both.
```

## Safety Features

- ✅ Interactive approval for each action
- ⚠️ Extra confirmation for destructive actions
- 🔍 Dry run mode to preview changes
- 🔒 Permission and name validation
- 📝 Detailed logging and error reporting

## Limitations

- Cannot archive:
  - The general/default channel
  - Required channels
  - Channels where you're not a member (unless you're an admin)
- Redirect notices:
  - Will attempt to post when archiving with a target channel
  - If posting fails (e.g., not a member of the channel), a warning is shown and archiving continues
  - Target channel must exist and not be archived
- Cannot rename:
  - Archived channels
  - Channels without proper permissions (unless you're an admin)
  - To names that already exist
- Channel names must be:
  - Lowercase
  - No spaces or periods
  - Max 80 characters
  - Only letters, numbers, hyphens, underscores
- Google Sheets specific:
  - Requires a Google Cloud Project
  - Service account must have editor access to the sheet
  - Sheet URL must be in the correct format

## Debugging

- Use VSCode's debug configurations (included in `.vscode/launch.json`)
- Check the Slack API responses for detailed error messages
- Use `--dry-run` to validate changes before executing
- Review version history (Google Sheets) or backup files (CSV) if needed
- For Google Sheets specific issues:
  - Verify service account permissions
  - Check sheet sharing settings
  - Ensure sheet URL is correct

## Contributing

Contributions are welcome! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests

## Security Note

- Never commit your `.env` file or `service-account.json`
- Keep your Slack token secure
- Review changes carefully before execution
- Consider running `--dry-run` first
- For Google Sheets:
  - Keep service account credentials secure
  - Only share sheets with necessary users
  - Regularly review service account access