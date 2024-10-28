// After Effects script to add markers based on CSV timestamps
var file = File.openDialog("Select your converted CSV file");

if (file) {
    file.open("r");

    // Read the active composition
    var comp = app.project.activeItem;

    // Check if the active item is a composition
    if (comp instanceof CompItem) {

        // Loop through each line in the CSV
        while (!file.eof) {
            var line = file.readln();

            // Remove any leading or trailing whitespace manually
            line = line.replace(/^\s+|\s+$/g, "");

            // Skip empty lines, if any
            if (line === "") continue;

            // Convert line to a float representing seconds
            var seconds = parseFloat(line);

            // Add a marker at the specific time if it's a valid number
            if (!isNaN(seconds)) {
                var marker = new MarkerValue("Highlight");
                comp.markerProperty.setValueAtTime(seconds, marker);
            }
        }

        file.close();
        alert("Markers added to the composition.");
    } else {
        alert("Please select a composition in the project.");
    }
} else {
    alert("No file selected.");
}
