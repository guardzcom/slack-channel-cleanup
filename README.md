# Slack Channel Cleanup

A Python script to manage Slack channels in bulk, supporting operations like renaming, archiving, and merging channels.

## Prerequisites

- Python 3.6+
- A Slack user token (xoxp) with the following required scopes:
  - `channels:read` - For listing public channels
  - `groups:read` - For listing private channels
  - `channels:write` - For managing public channels
  - `groups:write` - For managing private channels
  - `chat:write` - For posting messages (used for merge notifications)

## Installation

1. Clone this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Create a `.env` file in the root directory with your Slack user token:
```
SLACK_TOKEN=xoxp-your-token-here
```

## Usage

The script operates in two modes:

### 1. Export Mode

Export all channels to a CSV file for review:

```bash
python -m src.channel_renamer export [-f output.csv]
```

This will create a CSV file with all channels and their properties. The CSV includes the following columns:
- `channel_id`: Slack's internal channel ID
- `name`: Channel name
- `is_private`: Whether the channel is private
- `member_count`: Number of members
- `created_date`: Channel creation date
- `action`: Action to perform (default: "keep")
- `target_value`: Additional value for merge/rename actions
- `notes`: Optional notes/comments

### 2. Execute Mode

After reviewing and editing the CSV file, run the actions:

```bash
python -m src.channel_renamer execute -f channels.csv [-y] [-d]
```

Options:
- `-y, --yes`: Skip initial confirmation prompt
- `-d, --dry-run`: Show what would be done without making any changes

### Supported Actions

In the CSV file, set the `action` column to one of:

1. `keep` (default): No action, keep the channel as is
2. `archive`: Archive the channel
   - Cannot archive the general channel or required channels
   - User must be a member of the channel
3. `merge`: Archive the channel and post a message directing users to another channel
   - Set `target_value` to the destination channel name (with or without #)
   - Target channel must exist
   - Bot must be a member of both channels
4. `rename`: Rename the channel
   - Set `target_value` to the new channel name (without #)
   - Names must be lowercase, max 80 characters
   - Only letters, numbers, hyphens, and underscores allowed
   - Cannot rename archived channels
   - Only channel creators, workspace admins, or channel managers can rename

## Features

- Supports both public and private channels
- CSV-based workflow for careful review before execution
- Interactive approval process for each action
- Validates channel names and permissions before executing actions
- Performs dry run summary before execution
- Respects Slack API rate limits
- Handles pagination for large workspaces
- Creates backup of CSV file before processing
- Provides detailed error messages for common issues

## Error Handling

The script handles various error cases:
- Missing required scopes
- Invalid channel names or formats
- Non-existent target channels for merges
- Permission issues (not in channel, not authorized)
- Rate limiting and API errors
- Workspace restrictions (required channels, general channel)
- Invalid CSV format or missing required columns
- Already archived or renamed channels

## Safety Features

1. Two-phase execution (export then execute)
2. CSV review step for careful planning
3. Action summary before execution
4. Confirmation prompt before making changes
5. Backup of CSV file before processing
6. Interactive approval for each action
7. Extra confirmation for destructive actions
8. Detailed logging of all actions
9. Success/failure reporting for each operation
10. Dry run mode for testing

## Debugging

The script includes VSCode launch configurations for both export and execute modes. Use the Debug view in VSCode to:
- Set breakpoints
- Step through code
- Inspect variables
- Debug configuration issues

## Common Issues

1. **Token Validation**: Ensure your token has all required scopes. The script will show which scopes are missing.
2. **Channel Access**: The bot must be invited to channels before it can manage them.
3. **Permission Errors**: 
   - Only certain users can rename channels
   - Cannot archive the general channel
   - Cannot archive required channels
4. **Rate Limits**: The script respects Slack's rate limits but may pause if limits are reached. 