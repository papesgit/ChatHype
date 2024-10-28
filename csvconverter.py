import csv

# Input and output file paths
input_file = "sodascpfinal.csv"   # Your original CSV file
output_file = "converted_timestamps.csv"  # Output file for After Effects script

def timestamp_to_seconds(timestamp):
    # Split the timestamp string by colon
    hours, minutes, seconds = map(int, timestamp.split(":"))
    # Calculate total seconds
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds

def convert_csv(input_file, output_file):
    with open(input_file, "r") as csv_in, open(output_file, "w", newline="") as csv_out:
        reader = csv.reader(csv_in)
        writer = csv.writer(csv_out)

        # Skip header row if present in input file
        header = next(reader, None)
        if header:
            print(f"Skipping header: {header}")

        for row in reader:
            try:
                # Assuming the timestamp is in the 5th column (index 4)
                timestamp = row[4]
                total_seconds = timestamp_to_seconds(timestamp)
                # Write only the timestamp in seconds to the output file
                writer.writerow([total_seconds])
            except (ValueError, IndexError) as e:
                print(f"Skipping row due to error: {e}")

    print(f"Converted timestamps saved to {output_file}")

# Run the conversion
convert_csv(input_file, output_file)
