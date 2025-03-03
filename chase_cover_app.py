import streamlit as st
import matplotlib.pyplot as plt
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from PIL import Image
import ezdxf
import os
import tempfile
from dotenv import load_dotenv
import json
from datetime import datetime
import math

# Load environment variables
load_dotenv()

def create_dxf_buffer(width, length, flange_length, add_kickout, holes, project_name):
    doc = ezdxf.new("R2000")
    doc.header["$INSUNITS"] = 1  # 1 = inches
    msp = doc.modelspace()
    
    msp.add_polyline3d([(0, 0, 0), (width, 0, 0), (width, length, 0), (0, length, 0)], close=True)
    msp.add_polyline3d([(-flange_length, -flange_length, 0), (width + flange_length, -flange_length, 0),
                        (width + flange_length, length + flange_length, 0), (-flange_length, length + flange_length, 0)], close=True)
    if add_kickout:
        msp.add_polyline3d([(-flange_length - 0.5, -flange_length - 0.5, 0), (width + flange_length + 0.5, -flange_length - 0.5, 0),
                            (width + flange_length + 0.5, length + flange_length + 0.5, 0), (-flange_length - 0.5, length + flange_length + 0.5, 0)], close=True)
        msp.add_polyline3d([(-flange_length - 0.875, -flange_length - 0.875, 0), (width + flange_length + 0.875, -flange_length - 0.875, 0),
                            (width + flange_length + 0.875, length + flange_length + 0.875, 0), (-flange_length - 0.875, length + flange_length + 0.875, 0)], close=True)
    else:
        msp.add_polyline3d([(-flange_length - 0.375, -flange_length - 0.375, 0), (width + flange_length + 0.375, -flange_length - 0.375, 0),
                            (width + flange_length + 0.375, length + flange_length + 0.375, 0), (-flange_length - 0.375, length + flange_length + 0.375, 0)], close=True)
    
    for hole in holes:
        msp.add_circle((hole["x"], hole["y"]), hole["diameter"] / 2)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        doc.saveas(tmp.name)
        with open(tmp.name, "rb") as f:
            dxf_buffer = io.BytesIO(f.read())
    os.unlink(tmp.name)
    dxf_buffer.seek(0)
    return dxf_buffer

st.title("Chimney Cap Measurement Tool")

# Initialize session state
if "sketch_created" not in st.session_state:
    st.session_state.sketch_created = False
    st.session_state.fig2d = None
    st.session_state.jpg_buffer = None
    st.session_state.holes = []
    st.session_state.uploaded_files_data = []
    st.session_state.project_name = ""
    st.session_state.spark_details = ""
    st.session_state.spark_arrestor = False
    st.session_state.windband = False
    st.session_state.fit_tolerance = 0.25
    st.session_state.additional_notes = ""
    st.session_state.color = "Not Selected"
    st.session_state.custom_color = ""

# Fixed Project Name field at the top
project_name = st.text_input("Project Name (Owner name and/or property address)", 
                            value=st.session_state.project_name, 
                            help="Enter the owner’s name, property address, or both (e.g., 'Smith - 123 Main St')")

# Callback to update uploaded_files_data immediately
def update_uploaded_files():
    uploaded = st.session_state.get("photo_upload_key", [])
    st.session_state.uploaded_files_data = [(f.name, io.BytesIO(f.read())) for f in uploaded] if uploaded else []

# Single form wrapping inputs (excluding photo upload)
with st.form(key="measurement_form"):
    # Tabs
    tab1, tab2, tab3 = st.tabs(["📏 Dimensions", "🕳️ Holes", "⚙️ Options"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            width = st.number_input("Width (Left to Right)", min_value=0.0, step=0.1, 
                                    help="Width of the chase cover base in inches")
        with col2:
            length = st.number_input("Length (Front to Back. Back is always cricket side)", min_value=0.0, step=0.1, 
                                     help="Length of the chase cover base in inches (back is cricket side)")
        
        fit_tolerance = st.number_input("Fit Tolerance (Total, not per side)", 
                                        min_value=0.0, step=0.05, value=st.session_state.fit_tolerance, format="%.2f", 
                                        help="Extra inches added to total width and length for fit (e.g., 0.25 adds 0.125 per side)")
        
        col3, col4 = st.columns(2)
        with col3:
            flange_length = st.number_input("Outer flange length (turndown)", min_value=0.0, step=0.1, 
                                            help="Length of the turndown flange in inches")
        with col4:
            add_kickout = st.checkbox("Add Kickout?", value=True, 
                                      help="Check to add kickout extensions (increases total size)")

    with tab2:
        with st.expander("Chimney Holes", expanded=True):
            num_holes = st.number_input("Number of Holes", min_value=1, max_value=10, step=1, value=1, 
                                        help="Number of chimney holes to specify")
            holes = []
            all_valid = True
            for i in range(num_holes):
                st.write(f"Hole {i + 1}")
                # Default calculated diameter
                diameter = 0.0
                x_pos = 0.0
                y_pos = 0.0
                diameter_x = 0.0
                diameter_y = 0.0
                
                collar_height = st.number_input("Collar Height", min_value=0.0, step=0.1, key=f"collar_{i}", 
                                                help="Height of the collar in inches")
                st.write("Enter at least 3 measurements:")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    left = st.number_input("Left Distance", min_value=0.0, step=0.1, key=f"left_{i}", 
                                           help="Distance from left edge to hole center in inches")
                with col2:
                    right = st.number_input("Right Distance", min_value=0.0, step=0.1, key=f"right_{i}", 
                                            help="Distance from right edge to hole center in inches")
                with col3:
                    back = st.number_input("Back Distance", min_value=0.0, step=0.1, key=f"back_{i}", 
                                           help="Distance from back edge to hole center in inches")
                with col4:
                    front = st.number_input("Front Distance", min_value=0.0, step=0.1, key=f"front_{i}", 
                                            help="Distance from front edge to hole center in inches")
                
                distances = {}
                if left > 0: distances["left"] = left
                if right > 0: distances["right"] = right
                if front > 0: distances["front"] = front
                if back > 0: distances["back"] = back
                
                if len(distances) >= 3:
                    if "left" in distances and "right" in distances:
                        diameter_x = width - distances["left"] - distances["right"]
                        x_pos = distances["left"] + diameter_x / 2
                    elif "left" in distances:
                        diameter_x = (width - distances["left"]) / 2
                        x_pos = distances["left"] + diameter_x / 2
                    elif "right" in distances:
                        diameter_x = (width - distances["right"]) / 2
                        x_pos = width - distances["right"] - diameter_x / 2
                    
                    if "front" in distances and "back" in distances:
                        diameter_y = length - distances["front"] - distances["back"]
                        y_pos = distances["back"] + diameter_y / 2
                        diameter = (diameter_x + diameter_y) / 2 if "left" in distances and "right" in distances else diameter_y
                    elif "back" in distances:
                        diameter = diameter_x
                        y_pos = distances["back"] + diameter / 2
                    elif "front" in distances:
                        diameter = diameter_x
                        y_pos = length - distances["front"] - diameter / 2
                else:
                    all_valid = False
                
                # Display Calculated Diameter result below title
                st.write(f"Calculated Diameter: {diameter:.2f} inches")
                measured_diameter = st.number_input("Measured Diameter (optional)", min_value=0.0, step=0.1, key=f"measured_diameter_{i}", 
                                                    help="Enter the manually measured diameter if different from calculated")
                
                # Check for diameter mismatch and display warning
                if ("left" in distances and "right" in distances) and ("front" in distances and "back" in distances):
                    if abs(diameter_x - diameter_y) > 0.1:  # Tolerance of 0.1 inches
                        st.warning(f"Hole {i+1}: Calculated diameters mismatch - Left-Right: {diameter_x:.2f} inches, Back-Front: {diameter_y:.2f} inches")
                
                # Use measured diameter if provided, else calculated
                final_diameter = measured_diameter if measured_diameter > 0 else diameter
                holes.append({"distances": distances, "diameter": final_diameter, "x": x_pos, "y": y_pos, "collar_height": collar_height, "measured_diameter": measured_diameter})

    with tab3:
        color = st.selectbox("Color", ["Not Selected", "White", "Black", "Med Bronze", "Mill", "Match Metal", "Other"], index=0, 
                             help="Select or specify the cap’s color")
        if color == "Other":
            custom_color = st.text_input("Custom Color", value=st.session_state.custom_color, 
                                        help="Specify a custom color if 'Other' is selected")
        else:
            custom_color = ""
        
        col5, col6 = st.columns(2)
        with col5:
            windband = st.checkbox("Windband", value=st.session_state.windband, 
                                  help="Check if a windband is required")
        with col6:
            spark_arrestor = st.checkbox("Spark Arrestor", value=st.session_state.spark_arrestor, 
                                        help="Check if a spark arrestor is needed")
        
        if spark_arrestor:
            spark_details = st.text_input("Spark Arrestor Details", value=st.session_state.spark_details, 
                                         help="Additional details for the spark arrestor (if applicable)")
        else:
            spark_details = ""
        
        additional_notes = st.text_area("Additional Notes", value=st.session_state.additional_notes, 
                                       help="Any extra notes for the shop")

    # Create Sketch button below tabs, inside form
    st.write("")  # Spacer
    submit_button = st.form_submit_button(label="Create Sketch")

# Upload Photos outside the form, below tabs
st.subheader("📷 Upload Photos")
st.file_uploader("Attach photos from the field", accept_multiple_files=True, type=["jpg", "png"], 
                 help="Upload photos from the field (JPG/PNG) - required before sending to shop", 
                 key="photo_upload_key", on_change=update_uploaded_files)

# Process Submission
if submit_button:
    if not all_valid:
        st.error("Please ensure at least 3 measurements are entered for each hole.")
    else:
        st.session_state.sketch_created = True
        st.session_state.holes = holes
        st.session_state.project_name = project_name
        st.session_state.spark_arrestor = spark_arrestor
        st.session_state.spark_details = spark_details
        st.session_state.windband = windband
        st.session_state.fit_tolerance = fit_tolerance
        st.session_state.additional_notes = additional_notes
        st.session_state.color = color
        st.session_state.custom_color = custom_color
        
        adjusted_width = width + fit_tolerance
        adjusted_length = length + fit_tolerance
        
        fig2d, ax2d = plt.subplots()
        ax2d.add_patch(plt.Rectangle((0, 0), adjusted_width, adjusted_length, fill=False, edgecolor="black", linestyle="-"))
        ax2d.add_patch(plt.Rectangle((-flange_length, -flange_length), adjusted_width + 2 * flange_length, 
                                     adjusted_length + 2 * flange_length, fill=False, edgecolor="blue", linestyle="-"))
        if add_kickout:
            ax2d.add_patch(plt.Rectangle((-flange_length - 0.5, -flange_length - 0.5), 
                                         adjusted_width + 2 * flange_length + 1, adjusted_length + 2 * flange_length + 1, 
                                         fill=False, edgecolor="black", linestyle="-"))
            ax2d.add_patch(plt.Rectangle((-flange_length - 0.875, -flange_length - 0.875), 
                                         adjusted_width + 2 * flange_length + 1.75, adjusted_length + 2 * flange_length + 1.75, 
                                         fill=False, edgecolor="gray", linestyle="-"))
        else:
            ax2d.add_patch(plt.Rectangle((-flange_length - 0.375, -flange_length - 0.375), 
                                         adjusted_width + 2 * flange_length + 0.75, adjusted_length + 2 * flange_length + 0.75, 
                                         fill=False, edgecolor="gray", linestyle="-"))
        
        for i, hole in enumerate(holes):
            ax2d.add_patch(plt.Circle((hole["x"], hole["y"]), hole["diameter"] / 2, fill=False, edgecolor="red", linestyle="-"))
            label = f"H{i+1}: D={hole['diameter']:.2f}"
            distances_label = "\n".join([f"{k[:1].upper()}={v:.2f}" for k, v in hole["distances"].items()])
            ax2d.text(hole["x"], hole["y"], f"{label}\n{distances_label}", ha="center", va="center", fontsize=8)
        
        ax2d.text(adjusted_width/2, -flange_length - 1, f"Width = {adjusted_width:.2f}", ha="center", va="top", fontsize=10)
        ax2d.text(-flange_length - 1, adjusted_length/2, f"Length = {adjusted_length:.2f}", ha="right", va="center", fontsize=10, rotation=90)
        ax2d.text(adjusted_width + flange_length + 1, adjusted_length/2, f"Flange = {flange_length:.2f}", ha="left", va="center", fontsize=8)
        
        ax2d.set_xlim(-flange_length - 2, adjusted_width + flange_length + 2)
        ax2d.set_ylim(-flange_length - 2, adjusted_length + flange_length + 2)
        ax2d.set_aspect("equal")
        ax2d.axis("off")
        ax2d.set_title(f"Chase Cover - {project_name or 'Unnamed Project'}")
        
        jpg_buffer = io.BytesIO()
        plt.savefig(jpg_buffer, format="jpg", dpi=300, bbox_inches="tight")
        jpg_buffer.seek(0)
        st.session_state.fig2d = fig2d
        st.session_state.jpg_buffer = jpg_buffer
        plt.close(fig2d)
        st.session_state.fig2d = None  # Reset fig2d to avoid reuse

# Display Persisted Outputs
if st.session_state.sketch_created and st.session_state.jpg_buffer:
    st.subheader("2D Sketch (Top-Down View with Measurements)")
    st.image(st.session_state.jpg_buffer.getvalue(), use_container_width=True)
    
    # Save Sketch button
    st.download_button(
        label="Save Sketch to Device",
        data=st.session_state.jpg_buffer,
        file_name=f"{st.session_state.project_name or 'chase_cover'}_sketch.jpg",
        mime="image/jpeg"
    )

    if st.session_state.uploaded_files_data:
        st.subheader("Uploaded Photos")
        for name, data in st.session_state.uploaded_files_data:
            data.seek(0)
            image = Image.open(data)
            st.image(image, caption=name, use_container_width=True)  # Updated to use_container_width

    st.subheader("Export Data")
    if not st.session_state.uploaded_files_data:
        st.warning("Please upload at least one photo before sending to shop.")
    send_button = st.button("✉️ Send to Shop", disabled=not bool(st.session_state.uploaded_files_data))
    if send_button and st.session_state.uploaded_files_data:
        try:
            sender_email = os.getenv("SENDER_EMAIL")
            sender_password = os.getenv("SENDER_PASSWORD")
            recipient_email = "mark@primeroofingfl.com"
            if not sender_email or not sender_password:
                raise ValueError("Email credentials not set in environment variables.")
            
            dxf_buffer = create_dxf_buffer(adjusted_width, adjusted_length, flange_length, add_kickout, st.session_state.holes, st.session_state.project_name)
            
            total_width = adjusted_width + 2 * flange_length + (1.75 if add_kickout else 0.75)
            total_length = adjusted_length + 2 * flange_length + (1.75 if add_kickout else 0.75)
            
            msg = MIMEMultipart()
            msg["From"] = sender_email
            msg["To"] = recipient_email
            msg["Subject"] = f"Chimney Cap Measurements - {st.session_state.project_name or 'Unnamed Project'}"
            
            body = "Chase Cover Measurements:\n\n"
            body += f"Project Name: {st.session_state.project_name or 'Unnamed Project'}\n"
            body += f"Length (Front to Back): {length:.2f} inches (Adjusted: {adjusted_length:.2f} inches with {fit_tolerance:.2f}\" tolerance)\n"
            body += f"Width (Left to Right): {width:.2f} inches (Adjusted: {adjusted_width:.2f} inches with {fit_tolerance:.2f}\" tolerance)\n"
            if total_length >= 48 or total_width >= 48:
                body += "**REQUIRES MORE THAN 1 SHEET TO FABRICATE**\n"
            body += f"Outer flange length (turndown): {flange_length:.2f} inches\n"
            body += f"Add Kickout: {add_kickout}\n"
            body += f"Color: {st.session_state.color}"
            if st.session_state.color == "Other":
                body += f" ({st.session_state.custom_color})\n"
            else:
                body += "\n"
            body += f"Windband: {st.session_state.windband}\n"
            body += f"Spark Arrestor: {st.session_state.spark_arrestor}"
            if st.session_state.spark_arrestor:
                body += f" - Details: {st.session_state.spark_details}\n"
            else:
                body += "\n"
            body += "Holes:\n"
            for i, hole in enumerate(st.session_state.holes):
                circumference = math.pi * hole["diameter"]
                body += f"  Hole {i+1}: Diameter={hole['diameter']:.2f} inches, Circumference={circumference:.2f} inches, Collar Height={hole['collar_height']:.2f} inches"
                if hole["measured_diameter"] > 0:
                    body += f", Measured Diameter={hole['measured_diameter']:.2f} inches"
                body += "\n"
                for side, dist in hole["distances"].items():
                    body += f"    Distance from {side.capitalize()}: {dist:.2f} inches\n"
            body += f"Additional Notes: {st.session_state.additional_notes or 'None'}\n"
            msg.attach(MIMEText(body, "plain"))
            
            for name, data in st.session_state.uploaded_files_data:
                data.seek(0)
                attachment = MIMEApplication(data.read(), _subtype="png")
                attachment.add_header("Content-Disposition", "attachment", filename=name)
                msg.attach(attachment)
            
            st.session_state.jpg_buffer.seek(0)
            jpg_attachment = MIMEApplication(st.session_state.jpg_buffer.read(), _subtype="jpg")
            jpg_attachment.add_header("Content-Disposition", "attachment", filename=f"{st.session_state.project_name or 'chase_cover'}_sketch.jpg")
            msg.attach(jpg_attachment)
            
            dxf_buffer.seek(0)
            attachment = MIMEApplication(dxf_buffer.read(), _subtype="dxf")
            attachment.add_header("Content-Disposition", "attachment", filename=f"{st.session_state.project_name or 'chase_cover'}.dxf")
            msg.attach(attachment)
            
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
            st.success("Data, photos, JPG, and DXF sent to Prime Roofing Shop")

            # Autosave JSON only
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"{st.session_state.project_name or 'chase_cover'}_{timestamp}"
            
            data_to_save = {
                "project_name": st.session_state.project_name,
                "width": width,
                "length": length,
                "fit_tolerance": fit_tolerance,
                "flange_length": flange_length,
                "add_kickout": add_kickout,
                "holes": [{**hole, "circumference": math.pi * hole["diameter"]} for hole in st.session_state.holes],
                "color": st.session_state.color,
                "custom_color": st.session_state.custom_color,
                "windband": st.session_state.windband,
                "spark_arrestor": st.session_state.spark_arrestor,
                "spark_details": st.session_state.spark_details,
                "additional_notes": st.session_state.additional_notes
            }
            json_buffer = io.BytesIO(json.dumps(data_to_save, indent=2).encode('utf-8'))
            st.download_button(
                label="Download Saved Data JSON",
                data=json_buffer,
                file_name=f"{base_filename}_data.json",
                mime="application/json",
                key=f"json_download_{timestamp}"
            )

        except Exception as e:
            st.error(f"Failed to send email: {e}")

st.sidebar.header("Instructions")
st.sidebar.write("""
1. Enter project name at the top.
2. Fill in dimensions, holes, and options across the tabs.
3. Add at least 3 hole measurements in the 'Holes' tab.
4. Upload photos below tabs (required before sending).
5. Click 'Create Sketch' below tabs to see the 2D sketch.
6. Use 'Save Sketch to Device' to save the JPG or 'Send to Shop' (below 'Export Data') to email data, photos, and DXF with JSON autosave.
""")