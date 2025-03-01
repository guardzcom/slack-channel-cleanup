#!/usr/bin/env python3

import os
import asyncio
import argparse
from datetime import datetime
from src.channel_manager import (
    get_all_channels,
    execute_channel_actions
)
from src.channel_csv import (
    read_channels_from_csv,
    create_csv_writer
)
from src.sheet_manager import SheetManager
from src.channel_actions import ChannelAction
from slack_sdk.errors import SlackApiError

async def main():
    """Main function to run the channel management script."""
    parser = argparse.ArgumentParser(description="Slack Channel Management Tool")
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
    
    args = parser.parse_args()
    
    if not args.file and not args.sheet:
        parser.error("Either --file or --sheet must be specified")
    if args.file and args.sheet:
        parser.error("Cannot specify both --file and --sheet")
    
    try:
        # Read existing channels and process any actions
        channels = None
        if args.file and os.path.exists(args.file):
            print(f"Reading from: {args.file}")
            channels = read_channels_from_csv(args.file)
        elif args.sheet:
            print(f"Reading from: {args.sheet}")
            sheet = SheetManager(args.sheet)
            try:
                channels = sheet.read_channels()
            except ValueError:
                pass
        
        # Process any actions
        if channels:
            actions = {}
            for channel in channels:
                action = channel["action"]
                if action != ChannelAction.KEEP.value:
                    actions[action] = actions.get(action, 0) + 1
            
            if actions:
                print("\nFound actions to process:")
                for action, count in actions.items():
                    print(f"{action}: {count} channels")
                
                if args.dry_run:
                    print("\nDRY RUN MODE - No changes will be made")
                
                channels_to_process = [ch for ch in channels if ch["action"] != ChannelAction.KEEP.value]
                successful_channel_ids = await execute_channel_actions(
                    channels_to_process,
                    dry_run=args.dry_run
                )
                
                # Clear successful actions
                if not args.dry_run and successful_channel_ids:
                    for channel in channels:
                        if channel["channel_id"] in successful_channel_ids:
                            channel["action"] = ChannelAction.KEEP.value
                            channel["target_value"] = ""
        
        # Get current channels
        print("\nFetching current channels...")
        current_channels = await get_all_channels()
        
        # Convert to our format
        if not channels:
            channels = []
        
        # Update existing and add new channels
        current_ids = {ch["id"] for ch in current_channels}
        existing_ids = {ch["channel_id"] for ch in channels}
        
        # Add new channels
        for channel in current_channels:
            if channel["id"] not in existing_ids:
                channels.append({
                    "channel_id": channel["id"],
                    "name": channel["name"],
                    "is_private": str(channel["is_private"]).lower(),
                    "member_count": str(channel["num_members"]),
                    "created_date": datetime.fromtimestamp(float(channel["created"])).strftime("%Y-%m-%d"),
                    "action": ChannelAction.KEEP.value,
                    "target_value": "",
                    "notes": ""
                })
        
        # Write to spreadsheet
        if args.file:
            f, writer, _ = create_csv_writer(args.file)
            try:
                for channel in channels:
                    writer.writerow(channel)
            finally:
                f.close()
            print(f"\nUpdated: {args.file}")
        else:
            sheet = SheetManager(args.sheet)
            sheet.write_channels(channels)
            print(f"\nUpdated: {args.sheet}")
        
        print("\nNext steps:")
        print("1. Review the channels and set the 'action' column to one of:")
        print("   - keep: No changes (default)")
        print("   - archive: Archive the channel (optionally specify target in 'target_value')")
        print("   - rename: Rename the channel (specify new name in 'target_value')")
        print("2. For archive actions, optionally specify a target channel in 'target_value'")
        print("3. Run the script again to process your changes")
            
    except ValueError as e:
        print(f"Configuration error: {str(e)}")
    except SlackApiError as e:
        print(f"Slack API error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 