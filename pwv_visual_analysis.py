#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pulse Wave Velocity Measurement Script with Enhanced Doppler Processing

This script analyzes ultrasound images to calculate PWV using:
1. Direct extraction for ECG traces (working well)
2. Enhanced image processing for Doppler traces:
   - Contrast enhancement
   - Advanced noise reduction
   - Multi-stage filtering
3. Upstroke initiation detection for precise timing
4. Per-cardiac-cycle PWV measurements

Dependencies:
    - OpenCV (cv2)
    - NumPy
    - Matplotlib
    - SciPy
    - os
"""
import threading
import os

# Add these imports at the top with your existing imports
from PIL import Image, ImageTk
import cv2
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter
import os
import warnings

# Suppress common warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Path to the ultrasound image
image_path = "/Users/devinwilson/Desktop/ovxset1_pwv_1.png"  # Replace with the actual image path

# Output folder
output_folder = "ultrasound_results"
if not os.path.exists(output_folder):
    os.makedirs(output_folder)
    print(f"Created output folder: {output_folder}")

def get_calibration_from_image(image):
    """
    Extract calibration information from the ultrasound image.
    
    Args:
        image: The input ultrasound image
        
    Returns:
        tuple: seconds_per_pixel, distance_mm
    """
    height, width, _ = image.shape
    
    # Time calibration (bottom of image shows 0.0 to 0.8 seconds)
    time_scale_seconds = 0.8
    seconds_per_pixel = time_scale_seconds / width
    
    # Distance measurement from the scale in the image
    # This would be the distance between measurement points for PWV calculation
    distance_mm = 5.0  # Replace with the actual measured distance
    
    return seconds_per_pixel, distance_mm

def create_masks(image):
    """Create masks with cropped edges"""
    height, width, _ = image.shape
    
    # Define crop boundaries
    left_crop = 20
    right_crop = width - 120
    
    # Create masks for cropped image
    ecg_y_start = int(height * 0.8)
    ecg_y_end = int(height * 0.95)
    ecg_region = image[ecg_y_start:ecg_y_end, left_crop:right_crop]
    
    doppler_y_start = int(height * 0.4)
    doppler_y_end = int(height * 0.7)
    doppler_region = image[doppler_y_start:doppler_y_end, left_crop:right_crop]
    
    # Create ECG mask (green channel)
    hsv_ecg = cv2.cvtColor(ecg_region, cv2.COLOR_BGR2HSV)
    lower_green = np.array([40, 50, 50])
    upper_green = np.array([80, 255, 255])
    ecg_mask = cv2.inRange(hsv_ecg, lower_green, upper_green)
    
    regions = {
        'ecg_y_start': ecg_y_start,
        'ecg_y_end': ecg_y_end,
        'doppler_y_start': doppler_y_start,
        'doppler_y_end': doppler_y_end,
        'left_crop': left_crop,
        'right_crop': right_crop
    }
    
    return ecg_mask, doppler_region, regions

def extract_ecg_trace(mask, width):
    """
    Extract the ECG trace from the mask using direct extraction.
    
    Args:
        mask: ECG mask image
        width: Width of the image
        
    Returns:
        numpy.ndarray: Extracted ECG trace
    """
    # Create an empty trace array
    height = mask.shape[0]
    trace = np.zeros(width)
    
    # For each column in the mask
    for col in range(width):
        # Find all non-zero pixels in this column
        pixels = np.where(mask[:, col] > 0)[0]
        
        # If we found signal pixels in this column
        if len(pixels) > 0:
            # Use the top of the signal (minimum y-value)
            trace[col] = np.min(pixels)
        else:
            # No signal in this column, set to the maximum height (bottom of image)
            trace[col] = height
    
    # Invert the trace so that higher values = higher on the plot
    # (in image coordinates, smaller y = higher position)
    inverted_trace = height - trace
    
    # Normalize to set baseline at zero
    # Use the most common value as the baseline
    hist, bin_edges = np.histogram(inverted_trace, bins=50)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    baseline_value = bin_centers[np.argmax(hist)]
    
    # Subtract baseline to set it at zero
    normalized_trace = inverted_trace - baseline_value
    
    # Replace any negative values with zero (artifacts below baseline)
    normalized_trace = np.maximum(normalized_trace, 0)
    
    # Apply light smoothing to reduce noise while preserving upstroke initiation
    smoothed_trace = savgol_filter(normalized_trace, window_length=7, polyorder=2)
    
    return smoothed_trace

def enhance_doppler_region(doppler_region):
    """
    Apply advanced image processing to enhance the Doppler signal.
    
    Args:
        doppler_region: The Doppler region of the ultrasound image
        
    Returns:
        numpy.ndarray: Enhanced Doppler image
    """
    # Convert to grayscale
    gray = cv2.cvtColor(doppler_region, cv2.COLOR_BGR2GRAY)
    # Step 1: Apply noise reduction
    # Use Non-Local Means Denoising for better noise removal while preserving edges
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, searchWindowSize=21, templateWindowSize=7)

    
    # Step 2: Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(denoised)
    
    # Step 3: Apply bilateral filtering to further reduce noise while preserving edges
    bilateral = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)
    
    # Step 4: Apply Gaussian blur to reduce remaining noise
    blurred = cv2.GaussianBlur(bilateral, (5, 5), 0)
    
    # Step 5: Remove horizontal lines (0 mm/s line)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
    horizontal_lines = cv2.morphologyEx(blurred, cv2.MORPH_OPEN, horizontal_kernel)
    no_horizontal = cv2.subtract(blurred, horizontal_lines)
    
    # Step 6: Apply Otsu's thresholding for adaptive threshold determination
    _, otsu_thresh = cv2.threshold(no_horizontal, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Step 7: Apply adaptive thresholding for even better segmentation
    adaptive_thresh = cv2.adaptiveThreshold(
        no_horizontal, 
        255, 
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 
        11, 2
    )
    
    
    # Step 8: Combine Otsu and adaptive thresholds for better results
    combined_thresh = cv2.bitwise_or(otsu_thresh, adaptive_thresh)

    
    # Step 9: Clean up with morphological operations
    kernel = np.ones((3, 3), np.uint8)
    morph_cleaned = cv2.morphologyEx(combined_thresh, cv2.MORPH_OPEN, kernel)
    morph_cleaned = cv2.morphologyEx(morph_cleaned, cv2.MORPH_CLOSE, kernel)
 
    # Step 10: Apply edge detection to help with trace extraction
    edges = cv2.Canny(enhanced, 50, 150)
    
    
    # Return both the binary mask and the enhanced grayscale for different approaches
    return morph_cleaned, edges, no_horizontal

def extract_doppler_trace(enhanced_mask, edges, enhanced_gray, width):
    """Extract the Doppler trace using the enhanced image processing results."""
    height = enhanced_mask.shape[0]
    
    # Method 1: Try using the binary mask directly
    trace_from_mask = np.zeros(width)
    for col in range(min(width, 1000)):  # Truncate at position 1000
        pixels = np.where(enhanced_mask[:, col] > 0)[0]
        if len(pixels) > 0:
            trace_from_mask[col] = np.min(pixels)  # Top-most pixel
        else:
            trace_from_mask[col] = height
            
    # Fill remaining positions with the last valid value
    if width > 1000:
        trace_from_mask[1000:] = trace_from_mask[999]
            
    # Method 2: Try using the edges (with truncation)
    trace_from_edges = np.zeros(width)
    for col in range(min(width, 1000)):  # Truncate at position 1000
        pixels = np.where(edges[:, col] > 0)[0]
        if len(pixels) > 0:
            trace_from_edges[col] = np.min(pixels)
        else:
            trace_from_edges[col] = height
            
    # Fill remaining positions with the last valid value
    if width > 1000:
        trace_from_edges[1000:] = trace_from_edges[999]
    
    # Method 3: Try using intensity profile (with truncation)
    trace_from_intensity = np.zeros(width)
    for col in range(min(width, 1000)):  # Truncate at position 1000
        col_profile = enhanced_gray[:, col]
        for row in range(height):
            if col_profile[row] > np.mean(col_profile) + np.std(col_profile):
                trace_from_intensity[col] = row
                break
        else:
            trace_from_intensity[col] = height
            
    # Fill remaining positions with the last valid value
    if width > 1000:
        trace_from_intensity[1000:] = trace_from_intensity[999]

    
    # Try to determine the best method based on signal quality
    # Calculate signal quality metrics for each method
    mask_variance = float(np.var(trace_from_mask))
    edges_variance = float(np.var(trace_from_edges))
    intensity_variance = float(np.var(trace_from_intensity))

    print(f"Trace quality metrics - Mask: {mask_variance:.1f}, "
      f"Edges: {edges_variance:.1f}, "
      f"Intensity: {intensity_variance:.1f}")
    # Choose the method with highest variance (likely has the most signal)
    best_trace = None
    best_method = ""
    
    if mask_variance >= edges_variance and mask_variance >= intensity_variance:
        best_trace = trace_from_mask
        best_method = "mask"
    elif edges_variance >= mask_variance and edges_variance >= intensity_variance:
        best_trace = trace_from_edges
        best_method = "edges"
    else:
        best_trace = trace_from_intensity
        best_method = "intensity"
        
    print(f"Selected best trace extraction method: {best_method}")
    
    # Invert and normalize the best trace
    inverted_trace = height - best_trace
    
    # Remove outliers for better baseline estimation
    valid_points = (inverted_trace > 0) & (inverted_trace < height)
    if np.any(valid_points):
        # Use 10th percentile as baseline estimation
        baseline = np.percentile(inverted_trace[valid_points], 10)
    else:
        baseline = 0
        
    # Normalize to set baseline at zero
    normalized_trace = inverted_trace - baseline
    normalized_trace = np.maximum(normalized_trace, 0)  # Set negative values to zero
    
    # Apply smoothing to reduce noise while preserving important features
    window_length = min(11, len(normalized_trace) // 5 * 2 + 1)  # Must be odd
    if window_length < 3:
        window_length = 3
    
    try:
        smoothed_trace = savgol_filter(normalized_trace, window_length=window_length, polyorder=2)
    except Exception as e:
        print(f"Warning: Savgol filter failed ({e}), using raw normalized trace")
        smoothed_trace = normalized_trace
    
    
    return smoothed_trace

# Unused function
def detect_upstroke_initiations(trace, trace_name="trace", min_distance=100):
    """
    Detect the exact points where the trace begins rising from baseline.
    """
    # Calculate the first derivative (rate of change)
    derivative = np.gradient(trace)
    
    # Calculate the second derivative (acceleration)
    acceleration = np.gradient(derivative)
    
    # Calculate adaptive threshold for slope detection
    slope_threshold = np.percentile(np.abs(derivative), 90) * 0.2
    print(f"Adaptive slope threshold for {trace_name}: {slope_threshold}")
    
    # Define baseline threshold as 5% of max signal amplitude
    baseline_threshold = np.max(trace) * 0.05
    
    # Find potential upstroke initiation points
    candidates = []
    for i in range(5, len(trace)-5):
        if derivative[i] > slope_threshold and acceleration[i] > 0:
            if np.mean(derivative[i-5:i]) < slope_threshold * 0.3:
                if trace[i] <= baseline_threshold:
                    candidates.append((i, derivative[i]))
    
    # Sort and filter candidates
    candidates.sort(key=lambda x: x[1], reverse=True)
    filtered_points = []
    
    if candidates:
        filtered_points.append(candidates[0][0])
        for point, _ in candidates[1:]:
            if all(abs(point - p) >= min_distance for p in filtered_points):
                filtered_points.append(point)
    
    return sorted(filtered_points)    

    """
    Measure time difference between ECG and Doppler signals using improved trace extraction.
    
    Args:
        image_path: Path to the ultrasound image
        
    Returns:
        dict: Time difference measurements and analysis results
    """
    # Load the image
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Could not load image from {image_path}")
    
        # Get calibration
    seconds_per_pixel, distance_mm = get_calibration_from_image(image)

    # Create masks and get regions
    ecg_mask, doppler_region, regions = create_masks(image)

    # Extract ECG trace using the ECG mask’s width
    ecg_width  = ecg_mask.shape[1]
    ecg_trace  = extract_ecg_trace(ecg_mask, ecg_width)

    # Apply enhanced processing to Doppler region
    enhanced_mask, edges, enhanced_gray = enhance_doppler_region(doppler_region)

    # Extract Doppler trace using the enhanced mask’s width
    doppler_width  = enhanced_mask.shape[1]
    doppler_width = enhanced_gray.shape[1]
    doppler_trace = extract_doppler_trace(enhanced_mask, edges, enhanced_gray, doppler_width)
    # Detect upstroke initiations for both traces
    ecg_initiations     = detect_upstroke_initiations(ecg_trace,   "ECG")
    doppler_initiations = detect_upstroke_initiations(doppler_trace, "Doppler")
    
    print(f"Detected {len(ecg_initiations)} ECG upstroke initiations")
    print(f"Detected {len(doppler_initiations)} Doppler upstroke initiations")
    
    # Match ECG with subsequent Doppler initiations
    matched_pairs = []
    time_differences_ms = []
    
    for ecg_idx in ecg_initiations:
        # Find the nearest Doppler initiation after this ECG initiation
        next_doppler = [d for d in doppler_initiations if d > ecg_idx]
        if next_doppler:
            doppler_idx = min(next_doppler)
            
            # Calculate time difference in milliseconds
            time_diff_ms = (doppler_idx - ecg_idx) * seconds_per_pixel * 1000
            
            # Only include physiologically plausible time differences
            if 10 <= time_diff_ms <= 300:  # 10ms to 300ms is reasonable
                matched_pairs.append((ecg_idx, doppler_idx))
                time_differences_ms.append(time_diff_ms)

    
    return {
        'time_differences_ms': time_differences_ms,
        'average_time_diff_ms': np.mean(time_differences_ms) if time_differences_ms else 0,
        'report_path': report_path,
        'csv_path': csv_path,
        'visualization_path': output_path
    }

def main():
    root = tk.Tk()
    app = PWVUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()