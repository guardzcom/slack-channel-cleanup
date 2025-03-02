#!/usr/bin/env python3

import os
import asyncio
import argparse
from datetime import datetime
from src.channel_manager import (
    get_all_channels,
    execute_channel_actions
)
from src.channel_data import (
    read_channels_from_csv,
    create_csv_writer,
    create_channel_dict
)
from src.sheet_manager import SheetManager
from src.channel_actions import ChannelAction
from slack_sdk.errors import SlackApiError

async def main():
    """Main function to run the channel curation script."""
    parser = argparse.ArgumentParser(description="Slack Channel Curation Tool")
    parser.add_argument(
        "--file",
        "-f",
        help="Path to spreadsheet in CSV format"
    )
    parser.add_argument(
        "--sheet",
        help="URL of spreadsheet in Google Sheets format"
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Show what would be done without making any changes"
    )
    parser.add_argument(
        "--batch",
        "-b",
        type=int,
        default=10,
        help="Number of channels to confirm at once (0 for individual confirmation, default: 10)"
    )
    parser.add_argument(
        "--refresh",
        "-r",
        action="store_true",
        help="Force refresh of channel data (ignore cache)"
    )
    
    args = parser.parse_args()
    
    if not args.file and not args.sheet:
        parser.error("Either --file or --sheet must be specified")
    if args.file and args.sheet:
        parser.error("Cannot specify both --file and --sheet")
    
    try:
        # Initialize sheet curator if using Google Sheets
        sheet = None
        if args.sheet:
            print(f"Connecting to Google Sheets: {args.sheet}")
            sheet = SheetManager(args.sheet)
        
        # Read existing channels and process any actions
        channels = None
        if args.file and os.path.exists(args.file):
            print(f"Reading from: {args.file}")
            channels = read_channels_from_csv(args.file)
        elif sheet:
            print(f"Reading from: {args.sheet}")
            try:
                channels = sheet.read_channels()
            except ValueError as e:
                print(f"Error reading sheet: {str(e)}")
                if "Invalid action" in str(e) or "Target value is required" in str(e):
                    print("\nPlease fix the errors in your spreadsheet and try again.")
                    return
                # Only continue with empty list for new/empty sheets
                if "No values found" in str(e):
                    print("No existing channels found in sheet, will create new")
                    channels = []
                else:
                    raise  # Re-raise unexpected errors
        
        # Process any actions
        if channels:
            # Validate channel data
            invalid_channels = []
            for channel in channels:
                if not channel.get("channel_id"):
                    invalid_channels.append(f"Missing channel ID for {channel.get('name', 'UNKNOWN')}")
                if not channel.get("name"):
                    invalid_channels.append(f"Missing name for channel {channel.get('channel_id', 'UNKNOWN')}")
                if channel.get("action") == ChannelAction.ARCHIVE.value and channel.get("target_value"):
                    target = channel["target_value"].lstrip('#')
                    if not target.islower() or ' ' in target or '.' in target:
                        invalid_channels.append(
                            f"Invalid target channel format '{target}' for {channel['name']}. "
                            "Must be lowercase with no spaces or periods."
                        )
            
            if invalid_channels:
                print("\nFound invalid channel data:")
                for error in invalid_channels:
                    print(f"- {error}")
                print("\nPlease fix these issues and try again.")
                return
            
            actions = {}
            for channel in channels:
                action = channel["action"]
                if action != ChannelAction.KEEP.value and action != ChannelAction.NEW.value:
                    actions[action] = actions.get(action, 0) + 1
            
            if actions:
                print("\nFound actions to process:")
                for action, count in actions.items():
                    print(f"{action}: {count} channels")
                
                if args.dry_run:
                    print("\nDRY RUN MODE - No changes will be made")
                
                channels_to_process = [ch for ch in channels if ch["action"] != ChannelAction.KEEP.value and ch["action"] != ChannelAction.NEW.value]
                successful_channel_ids = await execute_channel_actions(
                    channels_to_process,
                    dry_run=args.dry_run,
                    batch_size=args.batch
                )
                
                # Clear successful actions
                if not args.dry_run and successful_channel_ids:
                    # Remove archived channels immediately
                    channels = [ch for ch in channels if 
                              ch["channel_id"] not in successful_channel_ids or 
                              ch["action"] != ChannelAction.ARCHIVE.value]
                    
                    # Update renamed channels and clear their actions
                    for channel in channels:
                        if channel["channel_id"] in successful_channel_ids:
                            if channel["action"] == ChannelAction.RENAME.value:
                                channel["name"] = channel["target_value"]
                            elif channel["action"] == ChannelAction.UPDATE_DESCRIPTION.value:
                                channel["description"] = channel["target_value"]
                            channel["action"] = ChannelAction.KEEP.value
                            channel["target_value"] = ""
                    
                    # Write back just the changes after actions
                    if args.file:
                        f, writer, _ = create_csv_writer(args.file)
                        try:
                            for channel in channels:
                                writer.writerow(channel)
                        finally:
                            f.close()
                        print(f"\nUpdated: {args.file}")
                    elif sheet:
                        sheet.write_channels(channels)
                        print(f"\nUpdated: {args.sheet}")
                    
                    # Exit after handling actions
                    return
        
        # If no actions were processed, do a full refresh of channels
        print("\nFetching current channels...")
        current_channels = await get_all_channels(force_refresh=args.refresh, dry_run=args.dry_run)
        
        # Convert to our format
        if not channels:
            channels = []
        
        # Track existing channel IDs
        existing_ids = {ch["channel_id"] for ch in channels}
        
        # Update existing and add new channels
        current_ids = {ch["id"] for ch in current_channels}
        
        # Remove channels that are no longer active
        channels = [ch for ch in channels if ch["channel_id"] in current_ids]
        
        # Update existing channels with fresh data from Slack
        for slack_channel in current_channels:
            channel_id = slack_channel["id"]
            # Find matching channel in our list
            existing_channel = next((ch for ch in channels if ch["channel_id"] == channel_id), None)
            if existing_channel:
                # Update description to keep in sync with Slack
                # Use create_channel_dict to ensure HTML entities are decoded
                temp_dict = create_channel_dict(slack_channel, is_new=False)
                existing_channel["description"] = temp_dict["description"]
                # Update name to keep in sync with Slack (unless a rename action is pending)
                if existing_channel["action"] != ChannelAction.RENAME.value:
                    existing_channel["name"] = slack_channel["name"]
                # Don't override any pending actions
        
        # Add new channels
        for channel in current_channels:
            if channel["id"] not in existing_ids:
                new_channel = create_channel_dict(channel, is_new=True)
                channels.append(new_channel)
        
        # Write to spreadsheet
        if args.file:
            f, writer, _ = create_csv_writer(args.file)
            try:
                for channel in channels:
                    writer.writerow(channel)
            finally:
                f.close()
            print(f"\nUpdated: {args.file}")
        elif sheet:  # Reuse existing sheet curator
            sheet.write_channels(channels)
            print(f"\nUpdated: {args.sheet}")
        
        print("\nNext steps:")
        print("1. Edit the spreadsheet and set actions:")
        print("   - `new` - Newly discovered channels that need review")
        print("   - `keep` - No changes (default for existing channels)")
        print("   - `archive` - Archive the channel (optionally specify target channel in 'target_value' for redirect notice)")
        print("   - `rename` - Rename channel (specify new name in 'target_value')")
        print("   - `update_description` - Update channel description (specify new description in 'target_value')")
        print("2. For archive actions, optionally specify a target channel in 'target_value' (redirect notice will be attempted)")
        print("3. Run the script again to process your changes")
            
    except ValueError as e:
        print(f"Configuration error: {str(e)}")
    except SlackApiError as e:
        print(f"Slack API error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 