#!/usr/bin/env python3

import asyncio
import argparse
from src.channel_manager import (
    get_all_channels,
    execute_channel_actions
)
from src.channel_csv import (
    export_channels_to_csv,
    read_channels_from_csv,
    create_csv_writer,
    write_channel_to_csv
)
from src.sheet_manager import SheetManager
from src.channel_actions import ChannelAction
from slack_sdk.errors import SlackApiError

async def main():
    """Main function to run the channel management script."""
    parser = argparse.ArgumentParser(description="Slack Channel Management Tool")
    parser.add_argument(
        "mode",
        choices=["export", "execute"],
        help="Mode of operation: 'export' to create or update a spreadsheet, 'execute' to run actions"
    )
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
        if args.mode == "export":
            print("Fetching channels...")
            channels = await get_all_channels()
            
            # Export to spreadsheet
            if args.file:
                filename = export_channels_to_csv(channels, args.file)
                print(f"\nChannels exported to: {args.file}")
            else:
                sheet = SheetManager(args.sheet)
                sheet.write_channels(channels)
                print(f"\nChannels exported to: {args.sheet}")
            
            print("\nNext steps:")
            print("1. Review the channels and set the 'action' column to one of:")
            print("   - keep: No changes (default)")
            print("   - archive: Archive the channel (optionally specify target in 'target_value')")
            print("   - rename: Rename the channel (specify new name in 'target_value')")
            print("2. For archive actions, optionally specify a target channel in 'target_value'")
            print(f"3. Run the script with 'execute' mode using the same spreadsheet")
            
        else:  # execute mode
            if args.file:
                print(f"Reading actions from spreadsheet: {args.file}")
                channels = read_channels_from_csv(args.file)
            else:
                print(f"Reading actions from spreadsheet: {args.sheet}")
                sheet = SheetManager(args.sheet)
                channels = sheet.read_channels()
            
            print(f"Found {len(channels)} channels to process")
            
            # Show summary of actions
            actions = {}
            for channel in channels:
                action = channel["action"]
                actions[action] = actions.get(action, 0) + 1
            
            print("\nAction Summary:")
            for action, count in actions.items():
                print(f"{action}: {count} channels")
            
            if args.dry_run:
                print("\nDRY RUN MODE - No changes will be made")
            
            # Execute actions
            channels_to_process = [ch for ch in channels if ch["action"] != ChannelAction.KEEP.value]
            successful_channel_ids = await execute_channel_actions(
                channels_to_process,
                dry_run=args.dry_run
            )
            
            # Update after execution
            if not args.dry_run and successful_channel_ids:
                print("\nUpdating spreadsheet...")
                
                # Clear actions for successful channels
                for channel in channels:
                    if channel["channel_id"] in successful_channel_ids:
                        channel["action"] = ChannelAction.KEEP.value
                        channel["target_value"] = ""
                
                # Write back to spreadsheet
                if args.file:
                    f, writer, _ = create_csv_writer(args.file)
                    try:
                        for channel in channels:
                            writer.writerow(channel)
                    finally:
                        f.close()
                else:
                    sheet = SheetManager(args.sheet)
                    sheet.write_channels(channels)
                
                print(f"Actions cleared for {len(successful_channel_ids)} successfully processed channels.")
            
    except ValueError as e:
        print(f"Configuration error: {str(e)}")
    except SlackApiError as e:
        print(f"Slack API error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 