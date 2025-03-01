import os
import asyncio
import json
import time
import sys
from typing import List, Dict, Optional
from slack_sdk.errors import SlackApiError
from .slack_client import get_slack_client
from .channel_data import (
    read_channels_from_csv,
    create_csv_writer,
    write_channel_to_csv
)
from .sheet_manager import SheetManager
from .channel_actions import ChannelActionHandler, ChannelAction
from datetime import datetime

# Cache file path (in project directory)
CACHE_FILE = "channel_activity_cache.json"
# Cache expiration in seconds (24 hours)
CACHE_EXPIRATION = 86400

async def fetch_channel_history(client, channel: Dict) -> None:
    """Fetch history for a single channel."""

    channel_name = channel.get('name', channel.get('id', 'UNKNOWN'))
    
    try:
        # Add retry logic for rate limits
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                history = client.conversations_history(
                    channel=channel["id"],
                    limit=20,  # Fetch more messages to ensure we get at least one actual message
                    include_all_metadata=False  # We only need the timestamp
                )
                
                # Filter for actual messages (not system messages)
                messages = [msg for msg in history.get("messages", []) 
                           if not msg.get("subtype")]
                if messages:
                    # messages are already sorted by timestamp (newest first)
                    channel["latest"] = messages[0]
                return
                
            except SlackApiError as e:
                if e.response.get("error") == "rate_limited":
                    retry_count += 1
                    retry_after = int(e.response.get("headers", {}).get("Retry-After", 5))
                    print(f"    ⚠️  Rate limited when fetching history for #{channel_name}, waiting {retry_after}s (retry {retry_count}/{max_retries})")
                    await asyncio.sleep(retry_after)
                else:
                    # For non-rate limit errors, raise to outer exception handler
                    raise
                    
        # If we've exhausted retries
        if retry_count >= max_retries:
            print(f"    ⚠️  Failed to fetch history for #{channel_name} after {max_retries} retries")
            
    except SlackApiError as e:
        print(f"    ⚠️  Could not fetch history for #{channel_name}: {e.response.get('error', 'unknown error')}")
    except Exception as e:
        print(f"    ⚠️  Error fetching history for #{channel_name}: {str(e)}")

def load_cache() -> Dict:
    """Load channel activity data from cache file if it exists and is not expired."""
    if not os.path.exists(CACHE_FILE):
        return {}
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
        
        # Check if cache is expired
        if time.time() - cache.get('timestamp', 0) > CACHE_EXPIRATION:
            print("Cache is expired, will fetch fresh data")
            return {}
        
        return cache
    except Exception as e:
        print(f"Warning: Could not load cache: {str(e)}")
        return {}

def save_cache(channels: List[Dict]) -> None:
    """Save channel activity data to cache file."""
    try:
        # Extract only the channel ID and last activity data
        activity_data = {}
        for channel in channels:
            try:
                if channel.get("latest") and channel.get("id"):
                    activity_data[channel["id"]] = {
                        "ts": channel["latest"].get("ts"),
                        "text": channel["latest"].get("text", "")[:50]  # Store truncated message text for reference
                    }
            except Exception:
                # Skip this channel if there's any issue
                continue
        
        cache = {
            'timestamp': time.time(),
            'activity': activity_data
        }
        
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
        
        print(f"Cached activity data for {len(activity_data)} channels to {CACHE_FILE}")
    except Exception as e:
        print(f"Warning: Could not save cache: {str(e)}")

def apply_cached_activity(channels: List[Dict], cache: Dict) -> None:
    """Apply cached activity data to channel list."""
    if not cache or 'activity' not in cache:
        return
    
    activity_data = cache['activity']
    applied_count = 0
    
    for channel in channels:
        # Make sure channel has an id before trying to access it
        if channel.get("id") and channel["id"] in activity_data:
            try:
                # Create a minimal "latest" structure with just the timestamp
                channel["latest"] = {"ts": activity_data[channel["id"]]["ts"]}
                applied_count += 1
            except (KeyError, TypeError):
                # Skip if there's any issue with the cached data
                continue
    
    if applied_count > 0:
        print(f"Applied cached activity data to {applied_count} channels")

async def get_all_channels(csv_writer=None, use_cache: bool = True, force_refresh: bool = False, dry_run: bool = False) -> List[Dict]:
    """
    Fetch all active channels (public and private) from Slack workspace.
    Returns a list of channel dictionaries.
    
    Args:
        csv_writer: Optional CSV writer to write channels as they're fetched
        use_cache: Whether to use cached data if available
        force_refresh: Whether to force a refresh of the data
        dry_run: Whether this is a dry run (won't save cache)
    """
    client = get_slack_client()
    channels = []
    cursor = None
    page = 1
    rate_limit_count = 0
    
    # Load cache if not forcing refresh
    cache = {}
    if use_cache and not force_refresh:
        try:
            cache = load_cache()
        except Exception as e:
            print(f"Warning: Could not load cache: {str(e)}")
            cache = {}
    
    print("\nFetching channels (200 per page)...")
    while True:
        try:
            print(f"Fetching page {page}...")
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
                include_num_members=True
            )
            
            if not response["ok"]:
                raise SlackApiError("Failed to fetch channels", response)
            
            new_channels = response["channels"]
            
            # Safety check: validate channel data before adding
            for channel in new_channels:
                if not channel.get("id"):
                    print(f"⚠️  Warning: Skipping channel with missing ID")
                    continue
                if not channel.get("name"):
                    print(f"⚠️  Warning: Skipping channel with ID {channel.get('id')} - missing name")
                    continue
                channels.append(channel)
            
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            
            page += 1
            await asyncio.sleep(0.5)  # Increased delay between pages to avoid rate limits
            
        except SlackApiError as e:
            error_code = e.response.get("error", "unknown_error")
            if error_code == "rate_limited":
                rate_limit_count += 1
                if rate_limit_count > 3:
                    print("Too many rate limit errors, aborting")
                    raise
                retry_after = int(e.response.get("headers", {}).get("Retry-After", 10))
                print(f"Rate limited. Waiting {retry_after} seconds...")
                await asyncio.sleep(retry_after)
                continue
            elif error_code in ["missing_scope", "invalid_auth"]:
                raise ValueError(
                    "Missing required scopes or invalid authentication. "
                    "Ensure your token has channels:read and groups:read scopes."
                )
            raise
    
    print(f"\nFetched {len(channels)} total channels")
    
    # Apply cached activity data if available
    if use_cache and not force_refresh and cache:
        apply_cached_activity(channels, cache)
        
        # Only fetch activity for channels without cached data
        channels_to_update = [ch for ch in channels if not ch.get("latest")]
        if channels_to_update:
            print(f"\nFetching last activity for {len(channels_to_update)} channels without cached data...")
            
            # Create tasks for concurrent history fetching
            tasks = []
            for i, channel in enumerate(channels_to_update, 1):
                try:
                    channel_name = channel.get('name', channel.get('id', 'UNKNOWN'))
                    print(f"  Queuing #{channel_name}...")
                    tasks.append(fetch_channel_history(client, channel))
                    if len(tasks) >= 10:  # Process in batches of 10
                        await asyncio.gather(*tasks)
                        tasks = []
                        await asyncio.sleep(0.2)  # Small delay between batches
                except Exception as e:
                    print(f"  ⚠️  Error queuing channel: {str(e)}")
                    continue
            
            # Process any remaining tasks
            if tasks:
                await asyncio.gather(*tasks)
        else:
            print("\nUsing cached activity data for all channels")
    else:
        # Fetch activity for all channels
        print(f"\nFetching last activity for {len(channels)} channels...")
        
        # Create tasks for concurrent history fetching
        tasks = []
        for i, channel in enumerate(channels, 1):
            try:
                channel_name = channel.get('name', channel.get('id', 'UNKNOWN'))
                print(f"  Queuing #{channel_name}...")
                tasks.append(fetch_channel_history(client, channel))
                if len(tasks) >= 10:  # Process in batches of 10
                    await asyncio.gather(*tasks)
                    tasks = []
                    await asyncio.sleep(0.2)  # Small delay between batches
            except Exception as e:
                print(f"  ⚠️  Error queuing channel: {str(e)}")
                continue
        
        # Process any remaining tasks
        if tasks:
            await asyncio.gather(*tasks)
    
    # Write to CSV if writer provided
    if csv_writer:
        for channel in channels:
            write_channel_to_csv(csv_writer, channel)
    
    # Save activity data to cache (skip if dry run)
    if not dry_run:
        save_cache(channels)
    
    return channels

async def get_channel_info(client, channel_id: str) -> Dict:
    """Get detailed channel information."""
    try:
        response = client.conversations_info(
            channel=channel_id,
            include_num_members=True  # Request member count in response
        )
        return response["channel"]
    except SlackApiError:
        return {}

async def get_user_approval(client, channel: Dict, action: str, target_value: Optional[str] = None, current_channels: Optional[List[Dict]] = None) -> bool:
    """
    Get user approval for a channel action.
    
    Args:
        client: Slack client
        channel: Channel to perform action on
        action: Action to perform
        target_value: Target value for action
        current_channels: List of all current channels (for validation)
        
    Returns:
        bool: Whether the action was approved
    """
    channel_id = channel["channel_id"]
    channel_name = channel["name"]
    
    # Get additional channel info
    try:
        channel_info = await get_channel_info(client, channel_id)
        
        # Format creation date
        created_ts = float(channel_info.get("created", 0))
        created_date = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d")
        
        # Get member count
        num_members = channel_info.get("num_members", "unknown")
        
        # Check if channel is private
        is_private = "Yes" if channel_info.get("is_private", False) else "No"
        
        # Check if channel is shared
        is_shared = "Yes" if channel_info.get("is_shared", False) else "No"
        
        # Get last activity
        last_activity = "unknown"
        if "latest" in channel_info and channel_info["latest"]:
            latest_ts = float(channel_info["latest"].get("ts", 0))
            if latest_ts > 0:
                last_activity = datetime.fromtimestamp(latest_ts).strftime("%Y-%m-%d")
                
                # Calculate days since last activity
                days_since = (datetime.now() - datetime.fromtimestamp(latest_ts)).days
                if days_since == 0:
                    last_activity += " (today)"
                elif days_since == 1:
                    last_activity += " (yesterday)"
                else:
                    last_activity += f" ({days_since} days ago)"
    except Exception as e:
        print(f"⚠️  Warning: Could not fetch additional info for #{channel_name}: {str(e)}")
        channel_info = {}
        created_date = "unknown"
        num_members = "unknown"
        is_private = "unknown"
        is_shared = "unknown"
        last_activity = "unknown"
    
    # Print channel info
    print(f"\n{'=' * 80}")
    print(f"Channel: #{channel_name} ({channel_id})")
    print(f"Created: {created_date}")
    print(f"Members: {num_members}")
    print(f"Private: {is_private}")
    print(f"Shared: {is_shared}")
    print(f"Last Activity: {last_activity}")
    
    # Print action info
    print(f"\nAction: {action.upper()}")
    if target_value:
        if action == ChannelAction.RENAME.value:
            print(f"New name: #{target_value}")
        elif action == ChannelAction.ARCHIVE.value:
            print(f"Redirect to: #{target_value}")
    
    # Print warning for destructive actions
    if action == ChannelAction.ARCHIVE.value:
        print("\n⚠️  WARNING: Archiving is permanent and cannot be undone by this script!")
        if is_shared == "Yes":
            print("⛔ CRITICAL: This is a shared channel. Archiving may affect external organizations!")
    
    # Print tip about Ctrl+C
    print("\nTip: Press Ctrl+C at any time to pause the process")
    
    # Get user approval
    while True:
        if action == ChannelAction.ARCHIVE.value:
            response = input("\nApprove this action? (y/n/a/q) [y=yes, n=no, a=yes to all, q=quit]: ").lower()
        else:
            response = input("\nApprove this action? (y/n/a/q) [y=yes, n=no, a=yes to all, q=quit]: ").lower()
        
        if response == "y" or response == "yes":
            return True
        elif response == "n" or response == "no":
            return False
        elif response == "a":
            print("Approving all remaining actions...")
            return "all"
        elif response == "q":
            print("Quitting...")
            sys.exit(0)
        else:
            print("Invalid response. Please enter y, n, a, or q.")

async def execute_channel_actions(channels: List[Dict], dry_run: bool = False, batch_size: int = 10) -> List[str]:
    """
    Execute actions on channels.
    
    Args:
        channels: List of channels to process
        dry_run: Whether to simulate execution without making changes
        batch_size: Number of channels to confirm at once (0 for individual confirmation)
        
    Returns:
        List[str]: List of channel IDs that were successfully processed
    """
    if not channels:
        print("No actions to execute.")
        return []
    
    # Initialize Slack client
    client = get_slack_client()
    
    # Create action handler
    handler = ChannelActionHandler(client)
    
    # Get current channels for validation
    print("Fetching current channel list for validation...")
    try:
        current_channels = await get_all_channels(use_cache=True, dry_run=dry_run)
    except Exception as e:
        print(f"Warning: Could not fetch current channels for validation: {str(e)}")
        current_channels = []
    
    # Count actions by type
    action_counts = {}
    for channel in channels:
        action = channel.get("action", "")
        action_counts[action] = action_counts.get(action, 0) + 1
    
    # Print summary
    print("\nPreparing to execute the following actions:")
    for action, count in action_counts.items():
        print(f"- {action.upper()}: {count} channels")
    
    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made")
    else:
        print("\n⚠️  LIVE MODE - Changes will be applied to your Slack workspace")
        
        # Check for mass archiving
        archive_count = action_counts.get(ChannelAction.ARCHIVE.value, 0)
        if archive_count > 10:
            print(f"\n⛔ WARNING: You are about to archive {archive_count} channels!")
            print("This is a destructive action that cannot be easily undone.")
            confirm = input("Type 'confirm-archive' to proceed or anything else to abort: ")
            if confirm != "confirm-archive":
                print("Aborting mass archive operation.")
                return []
    
    # Process channels
    successful_channel_ids = []
    yes_to_all = False
    
    # Sort channels by action priority
    def action_priority(channel):
        """Sort channels by action priority."""
        action = channel.get("action", "")
        # Process renames before archives
        if action == ChannelAction.RENAME.value:
            return 0
        elif action == ChannelAction.ARCHIVE.value:
            return 1
        else:
            return 2
    
    channels = sorted(channels, key=action_priority)
    
    # Process in batches if requested
    if batch_size > 0:
        for i in range(0, len(channels), batch_size):
            batch = channels[i:i+batch_size]
            
            # Print batch header
            print(f"\n{'=' * 80}")
            print(f"Processing batch {i//batch_size + 1} of {(len(channels) + batch_size - 1)//batch_size}")
            print(f"{'=' * 80}")
            
            # Print batch summary
            print("\nActions in this batch:")
            for channel in batch:
                action = channel.get("action", "")
                name = channel.get("name", "")
                target = channel.get("target_value", "")
                if target:
                    print(f"- {action.upper()} #{name} -> {target}")
                else:
                    print(f"- {action.upper()} #{name}")
            
            # Get batch approval if not yes_to_all
            if not yes_to_all:
                if dry_run:
                    response = input("\nReview this batch? (y/n/a/q) [y=yes, n=skip batch, a=yes to all, q=quit]: ").lower()
                else:
                    response = input("\nApprove this batch? (y/n/a/q) [y=yes, n=skip batch, a=yes to all, q=quit]: ").lower()
                
                if response == "n" or response == "no":
                    print("Skipping batch...")
                    continue
                elif response == "a":
                    print("Approving all remaining batches...")
                    yes_to_all = True
                elif response == "q":
                    print("Quitting...")
                    break
                # else proceed with batch
            
            # Process each channel in the batch
            for channel in batch:
                result = await process_single_channel(channel, handler, client, current_channels, dry_run, yes_to_all)
                if result == "success":
                    successful_channel_ids.append(channel["channel_id"])
                elif result == "all":
                    yes_to_all = True
    else:
        # Process channels individually
        try:
            for i, channel in enumerate(channels):
                print(f"\nProcessing channel {i+1} of {len(channels)}")
                result = await process_single_channel(channel, handler, client, current_channels, dry_run, yes_to_all)
                if result == "success":
                    successful_channel_ids.append(channel["channel_id"])
                elif result == "all":
                    yes_to_all = True
        except KeyboardInterrupt:
            print("\n\nProcess paused. What would you like to do?")
            response = input("Press Enter to continue, 'q' to quit, or 'a' to approve all remaining: ").lower()
            
            if response == 'q':
                print("Quitting...")
                return successful_channel_ids
            elif response == 'a':
                print("Approving all remaining actions...")
                yes_to_all = True
                
                # Process remaining channels with yes_to_all
                try:
                    for j in range(i, len(channels)):
                        channel = channels[j]
                        result = await process_single_channel(channel, handler, client, current_channels, dry_run, yes_to_all)
                        if result == "success":
                            successful_channel_ids.append(channel["channel_id"])
                except Exception as e:
                    print(f"Error processing remaining channels: {str(e)}")
    
    # Print summary
    print("\nExecution summary:")
    print(f"- Successfully processed: {len(successful_channel_ids)} channels")
    print(f"- Remaining: {len(channels) - len(successful_channel_ids)} channels")
    
    return successful_channel_ids

# Helper function to process a single channel
async def process_single_channel(channel, handler, client, current_channels, dry_run, yes_to_all):
    """Process a single channel and return the result status."""
    channel_name = f"#{channel['name']}"
    if channel.get("is_private"):
        channel_name = f"🔒 {channel_name}"
    
    action = channel.get("action", "").lower()
    action_message = {
        ChannelAction.KEEP.value: "keep as is",
        ChannelAction.ARCHIVE.value: "archive",
        ChannelAction.RENAME.value: "rename to"
    }.get(action, action)
    
    if action in [ChannelAction.ARCHIVE.value, ChannelAction.RENAME.value]:
        action_message = f"{action_message} {channel.get('target_value', '')}"
    
    if dry_run:
        print(f"✅ Would {action_message}: {channel_name}")
        return "success"
    
    # Verify channel still exists and is in expected state before executing
    try:
        channel_info = await get_channel_info(client, channel["channel_id"])
        if not channel_info:
            print(f"❌ Channel {channel['name']} no longer exists!")
            return "skipped"
        if channel_info.get("is_archived"):
            print(f"❌ Channel {channel['name']} is already archived!")
            return "skipped"
        if channel_info.get("name") != channel["name"]:
            print(f"❌ Channel has been renamed from {channel['name']} to {channel_info['name']}!")
            return "skipped"
            
        # Now execute the action
        result = await handler.execute_action(
            channel_id=channel["channel_id"],
            channel_name=channel["name"],
            action=action,
            target_value=channel.get("target_value", ""),
            current_channels=current_channels
        )
        
        if result.success:
            print(f"✅ {result.message}")
            
            # Update channel name in our data after successful rename
            if action == ChannelAction.RENAME.value:
                channel["name"] = channel.get("target_value")
            
            return "success"
        else:
            print(f"❌ {result.message}")
            return "failed"
    except Exception as e:
        print(f"❌ Error processing {channel['name']}: {str(e)}")
        return "skipped" 