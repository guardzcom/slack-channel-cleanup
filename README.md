# Slack Channel Cleanup

A Python script to manage Slack channels in bulk, supporting operations like renaming, archiving, and merging channels.

## Prerequisites

- Python 3.6+
- A Slack user token (xoxp) with the following required scopes:
  - `channels:write` - For managing public channels
  - `groups:write` - For managing private channels
  - `channels:read` - For listing public channels
  - `groups:read` - For listing private channels
  - `chat:write` - For posting messages (used for merge notifications)

Note: Bot tokens (xoxb) are not supported as they cannot manage channels.

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
python -m src.channel_renamer execute -f channels.csv
```

### Supported Actions

In the CSV file, set the `action` column to one of:

1. `keep` (default): No action, keep the channel as is
2. `archive`: Archive the channel
3. `merge`: Archive the channel and post a message directing users to another channel
   - Set `target_value` to the destination channel name (with or without #)
4. `rename`: Rename the channel
   - Set `target_value` to the new channel name (without #)

## Features

- Supports both public and private channels
- CSV-based workflow for careful review before execution
- Validates token type and required scopes
- Performs dry run summary before execution
- Respects Slack API rate limits
- Handles pagination for large workspaces
- Provides detailed error messages for common issues
- Supports bulk operations with different actions per channel

## Error Handling

The script handles various error cases:
- Invalid token type (must be a user token)
- Missing required scopes
- Invalid channel names
- Rate limiting
- Unauthorized access
- Already taken channel names
- Invalid CSV format or missing required columns
- Invalid actions or missing target values

## Safety Features

1. Two-phase execution (export then execute)
2. CSV review step for careful planning
3. Action summary before execution
4. Confirmation prompt before making changes
5. Detailed logging of all actions
6. Success/failure reporting for each operation 