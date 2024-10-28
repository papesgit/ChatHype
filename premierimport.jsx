// Premiere Pro script to add markers based on the original CSV format
var file = File.openDialog("Select your original CSV file");

if (file) {
    file.open("r");

    // Access the active sequence in Premiere Pro
    var activeSequence = app.project.activeSequence;

    if (activeSequence) {
        // Skip the header row if present
        var header = file.readln();
        if (header.includes("Start Time")) {
            header = file.readln(); // read the actual first data line if header exists
        }

        // Helper function to convert "hh:mm:ss" to seconds
        function timestampToSeconds(timestamp) {
            var timeParts = timestamp.split(":");
            var hours = parseInt(timeParts[0]);
            var minutes = parseInt(timeParts[1]);
            var seconds = parseInt(timeParts[2]);
            return hours * 3600 + minutes * 60 + seconds;
        }

        // Loop through each line in the CSV
        while (!file.eof) {
            var line = file.readln();

            // Remove any leading or trailing whitespace manually
            line = line.replace(/^\s+|\s+$/g, "");

            // Skip empty lines, if any
            if (line === "") continue;

            // Split the line by commas to extract columns
            var columns = line.split(",");

            // Ensure there are enough columns (timestamp should be in the 5th column)
            if (columns.length < 5) continue;

            // Get the timestamp (assumed in the 5th column)
            var timestamp = columns[4];

            // Convert timestamp "hh:mm:ss" to seconds
            var seconds = timestampToSeconds(timestamp);

            // Check if it's a valid number
            if (!isNaN(seconds)) {
                // Convert seconds to Premiere's time format (ticks)
                var time = new Time();
                time.seconds = seconds;

                // Add a marker at the specific time on the active sequence
                var marker = activeSequence.markers.createMarker(time);
                marker.name = "Moment Marker";
                marker.comments = "Automatically added marker at " + timestamp + " (seconds: " + seconds + ")";
            }
        }

        file.close();
        alert("Markers added to the sequence.");
    } else {
        alert("Please open a sequence in the project.");
    }
} else {
    alert("No file selected.");
}
