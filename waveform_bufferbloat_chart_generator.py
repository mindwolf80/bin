import matplotlib.pyplot as plt
import csv
import numpy as np  # Import numpy for creating the y-ticks range


def extract_latency_data(csv_file):
    """
    Extracts latency data (Mean, Median, 95th Percentile for Unloaded, During Download, During Upload)
    and the Bufferbloat grade from a CSV file.
    """
    unloaded_mean, unloaded_median, unloaded_95th = [], [], []
    download_mean, download_median, download_95th = [], [], []
    upload_mean, upload_median, upload_95th = [], [], []
    bufferbloat_grade = None

    try:
        with open(csv_file, newline="", encoding="utf-8") as file:
            reader = csv.reader(file)

            for row in reader:
                row = [item.strip() for item in row]  # Strip spaces from items

                # Capture the bufferbloat grade
                if "Bufferbloat Grade" in row:
                    bufferbloat_grade = row[1]

                # Capture mean, median, and 95th percentile latency data for each test type
                if "Unloaded - Mean Latency (ms)" in row:
                    try:
                        unloaded_mean.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "Unloaded - Median Latency (ms)" in row:
                    try:
                        unloaded_median.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "Unloaded - 95th %ile Latency (ms)" in row:
                    try:
                        unloaded_95th.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "During Download - Mean Latency (ms)" in row:
                    try:
                        download_mean.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "During Download - Median Latency (ms)" in row:
                    try:
                        download_median.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "During Download - 95th %ile Latency (ms)" in row:
                    try:
                        download_95th.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "During Upload - Mean Latency (ms)" in row:
                    try:
                        upload_mean.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "During Upload - Median Latency (ms)" in row:
                    try:
                        upload_median.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data
                elif "During Upload - 95th %ile Latency (ms)" in row:
                    try:
                        upload_95th.append(float(row[1]))
                    except ValueError:
                        pass  # Ignore invalid data

    except Exception as e:
        print(f"Error reading the file: {e}")
        return None, None, None, None, None, None, None, None

    # Return the extracted data
    return (
        unloaded_mean,
        unloaded_median,
        unloaded_95th,
        download_mean,
        download_median,
        download_95th,
        upload_mean,
        upload_median,
        upload_95th,
        bufferbloat_grade,
    )


def plot_latency_data(
    unloaded_mean,
    unloaded_median,
    unloaded_95th,
    download_mean,
    download_median,
    download_95th,
    upload_mean,
    upload_median,
    upload_95th,
    bufferbloat_grade,
):
    """
    Plots the mean, median, and 95th percentile latencies for Unloaded, During Download, and During Upload.
    Includes the Bufferbloat grade in the plot.
    """
    # Calculate the mean, median, and 95th percentile latency values
    mean_values = [
        sum(unloaded_mean) / len(unloaded_mean),
        sum(download_mean) / len(download_mean),
        sum(upload_mean) / len(upload_mean),
    ]
    median_values = [
        sum(unloaded_median) / len(unloaded_median),
        sum(download_median) / len(download_median),
        sum(upload_median) / len(upload_median),
    ]
    percentile_95_values = [
        sum(unloaded_95th) / len(unloaded_95th),
        sum(download_95th) / len(download_95th),
        sum(upload_95th) / len(upload_95th),
    ]

    latency_labels = ["Unloaded", "During Download", "During Upload"]

    # Plotting the data
    plt.figure(figsize=(10, 6))

    # Bar plots for each latency measure
    bar_width = 0.2
    index = range(len(latency_labels))

    # Plotting each latency metric
    plt.bar(index, mean_values, bar_width, label="Mean Latency", color="#ADD8E6")
    plt.bar(
        [i + bar_width for i in index],
        median_values,
        bar_width,
        label="Median Latency",
        color="#008080",
    )
    plt.bar(
        [i + 2 * bar_width for i in index],
        percentile_95_values,
        bar_width,
        label="95th Percentile Latency",
        color="#FF7F50",
    )

    # Add title and labels
    plt.title(
        f"Mean, Median, and 95th Percentile Latency Comparison (Bufferbloat Grade: {bufferbloat_grade})",
        fontsize=14,
    )
    plt.xlabel("Test Type", fontsize=12)
    plt.ylabel("Latency (ms)", fontsize=12)
    plt.xticks([i + bar_width for i in index], latency_labels)

    # Set y-axis ticks in steps of 5ms
    step = 5
    max_latency = (
        max(max(mean_values), max(median_values), max(percentile_95_values)) + 10
    )
    plt.ylim(0, max_latency)
    plt.yticks(np.arange(0, max_latency, step))  # Set ticks in steps of 5ms

    # Add legend
    plt.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3)

    # Adjust layout with custom parameters
    plt.subplots_adjust(
        top=0.909, bottom=0.165, left=0.062, right=0.99, hspace=0.2, wspace=0.2
    )

    # Display the plot
    plt.show()


def main():
    print("Please provide the path to your CSV file:")
    csv_file = input("CSV File Path: ")

    # Extract latency data and the Bufferbloat grade
    (
        unloaded_mean,
        unloaded_median,
        unloaded_95th,
        download_mean,
        download_median,
        download_95th,
        upload_mean,
        upload_median,
        upload_95th,
        bufferbloat_grade,
    ) = extract_latency_data(csv_file)

    # If valid data was found, plot it
    if unloaded_mean and download_mean and upload_mean and bufferbloat_grade:
        plot_latency_data(
            unloaded_mean,
            unloaded_median,
            unloaded_95th,
            download_mean,
            download_median,
            download_95th,
            upload_mean,
            upload_median,
            upload_95th,
            bufferbloat_grade,
        )
    else:
        print("No valid latency data or Bufferbloat grade found in the file.")


if __name__ == "__main__":
    main()
