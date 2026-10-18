import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
from io import StringIO

st.set_page_config(page_title="Network Performance Dashboard", layout="wide")


def create_gauge(value, title, max_value, color_threshold=None):
    if color_threshold is None:
        color_threshold = [0.33, 0.66]

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            title={"text": title},
            domain={"x": [0, 1], "y": [0, 1]},
            gauge={
                "axis": {"range": [None, max_value]},
                "bar": {"color": "darkblue"},
                "steps": [
                    {
                        "range": [0, max_value * color_threshold[0]],
                        "color": "lightgray",
                    },
                    {
                        "range": [
                            max_value * color_threshold[0],
                            max_value * color_threshold[1],
                        ],
                        "color": "gray",
                    },
                    {
                        "range": [max_value * color_threshold[1], max_value],
                        "color": "darkgray",
                    },
                ],
            },
        )
    )

    fig.update_layout(height=300)
    return fig


def create_latency_plot(unloaded, download, upload):
    fig = go.Figure()

    # Create time arrays for x-axis (sample numbers)
    x_unloaded = list(range(len(unloaded)))
    x_download = list(range(len(download)))
    x_upload = list(range(len(upload)))

    # Add traces for each type of latency
    fig.add_trace(
        go.Scatter(
            x=x_unloaded,
            y=unloaded,
            name="Unloaded Latency",
            mode="lines",
            line=dict(color="blue"),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x_download,
            y=download,
            name="Download Test Latency",
            mode="lines",
            line=dict(color="red"),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x_upload,
            y=upload,
            name="Upload Test Latency",
            mode="lines",
            line=dict(color="green"),
        )
    )

    fig.update_layout(
        title="Latency Measurements Over Time",
        xaxis_title="Sample Number",
        yaxis_title="Latency (ms)",
        height=500,
    )

    return fig


def create_latency_box_plot(unloaded, download, upload):
    fig = go.Figure()

    fig.add_trace(go.Box(y=unloaded, name="Unloaded", boxpoints="outliers"))
    fig.add_trace(go.Box(y=download, name="Download", boxpoints="outliers"))
    fig.add_trace(go.Box(y=upload, name="Upload", boxpoints="outliers"))

    fig.update_layout(
        title="Latency Distribution Analysis", yaxis_title="Latency (ms)", height=400
    )

    return fig


def parse_results(content):
    lines = content.split("\n")
    data = {}

    # Parse main metrics
    for line in lines:
        if "," in line:
            key, *values = line.split(",")
            data[key.strip()] = values[0] if len(values) == 1 else values

    # Parse latency measurements
    unloaded_latency = []
    download_latency = []
    upload_latency = []

    in_unloaded = False
    in_download = False
    in_upload = False

    for line in lines:
        if "====== UNLOADED LATENCY MEASUREMENTS (ms) ======" in line:
            in_unloaded = True
            continue
        elif "====== DOWNLOAD STAGE LATENCY MEASUREMENTS (ms) ======" in line:
            in_unloaded = False
            in_download = True
            continue
        elif "====== UPLOAD STAGE LATENCY MEASUREMENTS (ms) ======" in line:
            in_download = False
            in_upload = True
            continue
        elif "======" in line:
            in_unloaded = False
            in_download = False
            in_upload = False
            continue

        if in_unloaded and line.strip():
            try:
                unloaded_latency.append(float(line.strip()))
            except ValueError:
                continue
        elif in_download and line.strip():
            try:
                download_latency.append(float(line.strip()))
            except ValueError:
                continue
        elif in_upload and line.strip():
            try:
                upload_latency.append(float(line.strip()))
            except ValueError:
                continue

    data["unloaded_latency"] = unloaded_latency
    data["download_latency"] = download_latency
    data["upload_latency"] = upload_latency

    return data


def main():
    st.title("Network Performance Dashboard")

    uploaded_file = st.file_uploader("Upload your network test results", type=["csv"])

    if uploaded_file:
        content = StringIO(uploaded_file.getvalue().decode("utf-8")).read()
        data = parse_results(content)

        # Create three columns for the main metrics
        col1, col2, col3 = st.columns(3)

        with col1:
            st.plotly_chart(
                create_gauge(
                    float(data["Download speed (Mbps)"]),
                    "Download Speed (Mbps)",
                    1000,
                    [0.3, 0.6],
                ),
                use_container_width=True,
            )

        with col2:
            st.plotly_chart(
                create_gauge(
                    float(data["Upload speed (Mbps)"]),
                    "Upload Speed (Mbps)",
                    100,
                    [0.3, 0.6],
                ),
                use_container_width=True,
            )

        with col3:
            st.plotly_chart(
                create_gauge(
                    float(data["Mean Unloaded Latency (ms)"]),
                    "Mean Latency (ms)",
                    100,
                    [0.3, 0.6],
                ),
                use_container_width=True,
            )

        # Display Bufferbloat Grade
        st.subheader("Bufferbloat Grade")
        st.markdown(
            f"<h1 style='text-align: center; color: green;'>{data['Bufferbloat Grade']}</h1>",
            unsafe_allow_html=True,
        )

        # Display latency time series plot
        st.plotly_chart(
            create_latency_plot(
                data["unloaded_latency"],
                data["download_latency"],
                data["upload_latency"],
            ),
            use_container_width=True,
        )

        # Display latency distribution plot
        st.plotly_chart(
            create_latency_box_plot(
                data["unloaded_latency"],
                data["download_latency"],
                data["upload_latency"],
            ),
            use_container_width=True,
        )

        # Create a section for detailed metrics
        st.subheader("Detailed Metrics")
        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Increase In Mean Latency During Download Test (ms)",
                data["Increase In Mean Latency During Download Test (ms)"],
            )
            st.metric(
                "Unloaded - 95th %ile Latency (ms)",
                data["Unloaded - 95th %ile Latency (ms)"],
            )

        with col2:
            st.metric(
                "Increase In Mean During Upload Test (ms)",
                data["Increase In Mean During Upload Test (ms)"],
            )
            st.metric(
                "During Download - 95th %ile Latency (ms)",
                data["During Download - 95th %ile Latency (ms)"],
            )


if __name__ == "__main__":
    main()
