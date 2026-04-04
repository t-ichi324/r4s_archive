import os
import sys
import argparse
from pathlib import Path
from r4s.archive import R4SArchive, R4SKeyLen

def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def main():
    parser = argparse.ArgumentParser(description="R4S Archive Professional Manager v1.0")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Create Command ---
    p_create = subparsers.add_parser("create", help="Create a new encrypted archive")
    p_create.add_argument("path", type=str, help="Path to the new archive")
    p_create.add_argument("-p", "--password", type=str, help="Password for encryption")
    p_create.add_argument("-k", "--key-len", type=int, choices=[8, 16, 32], default=8, 
                          help="Key length (8:LOW, 16:MID, 32:HIGH)")

    # --- List Command ---
    p_list = subparsers.add_parser("list", help="List entries and assets in the archive")
    p_list.add_argument("path", type=str, help="Path to the archive")
    p_list.add_argument("-p", "--password", type=str, help="Password for access")

    # --- Add Command ---
    p_add = subparsers.add_parser("add", help="Add a file to the archive")
    p_add.add_argument("path", type=str, help="Path to the archive")
    p_add.add_argument("file", type=str, help="File path to add")
    p_add.add_argument("-l", "--logical-path", type=str, help="Logical path in archive")
    p_add.add_argument("-p", "--password", type=str, help="Password for access")

    # --- Optimize Command ---
    p_opt = subparsers.add_parser("optimize", help="Optimize and update archive security")
    p_opt.add_argument("path", type=str, help="Path to the archive")
    p_opt.add_argument("-p", "--password", type=str, help="Password for access")
    p_opt.add_argument("-k", "--new-key-len", type=int, choices=[8, 16, 32], 
                       help="New key length for migration")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "create":
            key_val = R4SKeyLen(args.key_len)
            arc = R4SArchive.create(args.path, args.password, key_len=key_val)
            print(f"Archive created: {args.path}")
            print(f"UID: {arc._uuid.hex()}")
            arc.close()

        elif args.command == "list":
            arc = R4SArchive.open(args.path, args.password)
            entries = arc.list_entries()
            assets = arc.list_assets()
            
            print(f"--- R4S Archive: {os.path.basename(args.path)} ---")
            print(f"Entries ({len(entries)}):")
            for uid, name in entries:
                meta = arc.get_entry_meta(uid)
                print(f"  [{uid:04d}] {name}")
            
            print(f"\nAssets ({len(assets)}):")
            for uid, name in assets:
                print(f"  [{uid:04d}] {name}")
            arc.close()

        elif args.command == "add":
            arc = R4SArchive.open(args.path, args.password)
            logical = args.logical_path or os.path.basename(args.file)
            uid = arc.set_entry(logical, args.file)
            arc.save()
            print(f"Added '{args.file}' as '{logical}' (UID: {uid})")
            arc.close()

        elif args.command == "optimize":
            arc = R4SArchive.open(args.path, args.password)
            new_key = R4SKeyLen(args.new_key_len) if args.new_key_len else None
            print("Optimizing archive structure and re-encrypting header...")
            arc.optimize(new_key_len=new_key)
            print("Optimization successful.")
            arc.close()

    except Exception as e:
        print(f"Error: {e}")
        if "--debug" in sys.argv:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
