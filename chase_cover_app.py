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

# Load environment variables
load_dotenv()

def create_dxf_buffer(width, length, flange_length, add_kickout, holes, project_name):
    doc = ezdxf.new("R2000")
    doc.header["$INSUNITS"] = 1  # 1 = inches
    msp = doc.modelspace()
    
    # Base rectangle (3D POLYLINE)
    msp.add_polyline3d([(0, 0, 0), (width, 0, 0), (width, length, 0), (0, length, 0)], close=True)
    # Flange rectangle
    msp.add_polyline3d([(-flange_length, -flange_length, 0), (width + flange_length, -flange_length, 0),
                        (width + flange_length, length + flange_length, 0), (-flange_length, length + flange_length, 0)], close=True)
    # Kickout rectangles
    if add_kickout:
        msp.add_polyline3d([(-flange_length - 0.5, -flange_length - 0.5, 0), (width + flange_length + 0.5, -flange_length - 0.5, 0),
                            (width + flange_length + 0.5, length + flange_length + 0.5, 0), (-flange_length - 0.5, length + flange_length + 0.5, 0)], close=True)
        msp.add_polyline3d([(-flange_length - 0.875, -flange_length - 0.875, 0), (width + flange_length + 0.875, -flange_length - 0.875, 0),
                            (width + flange_length + 0.875, length + flange_length + 0.875, 0), (-flange_length - 0.875, length + flange_length + 0.875, 0)], close=True)
    else:
        msp.add_polyline3d([(-flange_length - 0.375, -flange_length - 0.375, 0), (width + flange_length + 0.375, -flange_length - 0.375, 0),
                            (width + flange_length + 0.375, length + flange_length + 0.375, 0), (-flange_length - 0.375, length + flange_length + 0.375, 0)], close=True)
    
    # Circles for holes (2D entities, z=0)
    for hole in holes:
        msp.add_circle((hole["x"], hole["y"]), hole["diameter"] / 2)
    
    # Save to temp file then read into buffer
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
    st.session_state.uploaded_files_data = []  # Store photo data
    st.session_state.project_name = ""
    st.session_state.spark_details = ""
    st.session_state.spark_arrestor = False
    st.session_state.windband = False
    st.session_state.additional_notes = ""
    st.session_state.color = "Not Selected"
    st.session_state.custom_color = ""

# Outside Form: Inputs
project_name = st.text_input("Project Name (Homeowner name or address)", value=st.session_state.project_name)

col1, col2 = st.columns(2)
with col1:
    width = st.number_input("Width (Left to Right)", min_value=0.0, step=0.1)
with col2:
    length = st.number_input("Length (Front to Back. Back is always cricket side)", min_value=0.0, step=0.1)

col3, col4 = st.columns(2)
with col3:
    flange_length = st.number_input("Outer flange length (turndown)", min_value=0.0, step=0.1)
with col4:
    add_kickout = st.checkbox("Add Kickout?", value=True)

color = st.selectbox("Color", ["Not Selected", "White", "Black", "Med Bronze", "Mill", "Match Metal", "Other"], index=0)
if color == "Other":
    custom_color = st.text_input("Custom Color", value=st.session_state.custom_color)
else:
    custom_color = ""

col5, col6 = st.columns(2)
with col5:
    spark_arrestor = st.checkbox("Spark Arrestor", value=st.session_state.spark_arrestor)
with col6:
    windband = st.checkbox("Windband", value=st.session_state.windband)

if spark_arrestor:
    spark_details = st.text_input("Spark Arrestor Details", value=st.session_state.spark_details)
else:
    spark_details = ""

additional_notes = st.text_area("Additional Notes", value=st.session_state.additional_notes)

# Number of Holes
num_holes = st.number_input("Number of Holes", min_value=1, max_value=10, step=1, value=1)

with st.form(key="measurement_form"):
    # Chimney Holes Frame
    with st.expander("Chimney Holes", expanded=True):
        holes = []
        all_valid = True
        for i in range(num_holes):
            st.write(f"Hole {i + 1}")
            collar_height = st.number_input("Collar Height", min_value=0.0, step=0.1, key=f"collar_{i}")
            st.write("Enter at least 3 measurements:")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                left = st.number_input("Left Distance", min_value=0.0, step=0.1, key=f"left_{i}")
            with col2:
                right = st.number_input("Right Distance", min_value=0.0, step=0.1, key=f"right_{i}")
            with col3:
                front = st.number_input("Front Distance", min_value=0.0, step=0.1, key=f"front_{i}")
            with col4:
                back = st.number_input("Back Distance", min_value=0.0, step=0.1, key=f"back_{i}")
            
            distances = {}
            if left > 0:
                distances["left"] = left
            if right > 0:
                distances["right"] = right
            if front > 0:
                distances["front"] = front
            if back > 0:
                distances["back"] = back
            
            if len(distances) < 3:
                all_valid = False
            else:
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
                
                holes.append({"distances": distances, "diameter": diameter, "x": x_pos, "y": y_pos, "collar_height": collar_height})
    
    st.subheader("Upload Photos")
    uploaded_files = st.file_uploader("Attach photos from the field", accept_multiple_files=True, type=["jpg", "png"])
    submit_button = st.form_submit_button(label="Create Sketch")

# Process Submission
if submit_button:
    if not all_valid:
        st.error("Please ensure at least 3 measurements are entered for each hole.")
    else:
        # Store data in session state
        st.session_state.sketch_created = True
        st.session_state.holes = holes
        # Store photo data with names
        st.session_state.uploaded_files_data = [(f.name, io.BytesIO(f.read())) for f in uploaded_files] if uploaded_files else []
        st.session_state.project_name = project_name
        st.session_state.spark_arrestor = spark_arrestor
        st.session_state.spark_details = spark_details
        st.session_state.windband = windband
        st.session_state.additional_notes = additional_notes
        st.session_state.color = color
        st.session_state.custom_color = custom_color
        
        # 2D Sketch (Updated Colors)
        fig2d, ax2d = plt.subplots()
        ax2d.add_patch(plt.Rectangle((0, 0), width, length, fill=False, edgecolor="black", linestyle="-"))
        ax2d.add_patch(plt.Rectangle((-flange_length, -flange_length), width + 2 * flange_length, 
                                     length + 2 * flange_length, fill=False, edgecolor="blue", linestyle="-"))
        if add_kickout:
            ax2d.add_patch(plt.Rectangle((-flange_length - 0.5, -flange_length - 0.5), 
                                         width + 2 * flange_length + 1, length + 2 * flange_length + 1, 
                                         fill=False, edgecolor="black", linestyle="-"))
            ax2d.add_patch(plt.Rectangle((-flange_length - 0.875, -flange_length - 0.875), 
                                         width + 2 * flange_length + 1.75, length + 2 * flange_length + 1.75, 
                                         fill=False, edgecolor="gray", linestyle="-"))
        else:
            ax2d.add_patch(plt.Rectangle((-flange_length - 0.375, -flange_length - 0.375), 
                                         width + 2 * flange_length + 0.75, length + 2 * flange_length + 0.75, 
                                         fill=False, edgecolor="gray", linestyle="-"))
        
        for i, hole in enumerate(holes):
            ax2d.add_patch(plt.Circle((hole["x"], hole["y"]), hole["diameter"] / 2, fill=False, edgecolor="red", linestyle="-"))
            label = f"H{i+1}: D={hole['diameter']:.1f}"
            distances_label = "\n".join([f"{k[:1].upper()}={v:.1f}" for k, v in hole["distances"].items()])
            ax2d.text(hole["x"], hole["y"], f"{label}\n{distances_label}", ha="center", va="center", fontsize=8)
        
        ax2d.text(width/2, -flange_length - 1, f"Width = {width:.1f}", ha="center", va="top", fontsize=10)
        ax2d.text(-flange_length - 1, length/2, f"Length = {length:.1f}", ha="right", va="center", fontsize=10, rotation=90)
        ax2d.text(width + flange_length + 1, length/2, f"Flange = {flange_length:.1f}", ha="left", va="center", fontsize=8)
        
        ax2d.set_xlim(-flange_length - 2, width + flange_length + 2)
        ax2d.set_ylim(-flange_length - 2, length + flange_length + 2)
        ax2d.set_aspect("equal")
        ax2d.axis("off")
        ax2d.set_title(f"Chase Cover - {project_name or 'Unnamed Project'}")
        
        jpg_buffer = io.BytesIO()
        plt.savefig(jpg_buffer, format="jpg", dpi=300, bbox_inches="tight")
        jpg_buffer.seek(0)
        st.session_state.fig2d = fig2d
        st.session_state.jpg_buffer = jpg_buffer
        plt.close(fig2d)

# Display Persisted Outputs
if st.session_state.sketch_created:
    st.subheader("2D Sketch (Top-Down View with Measurements)")
    st.pyplot(st.session_state.fig2d)
    
    st.download_button(
        label="Download Sketch as JPG",
        data=st.session_state.jpg_buffer,
        file_name=f"{st.session_state.project_name or 'chase_cover'}_sketch.jpg",
        mime="image/jpeg"
    )

    # Generate DXF (R2000, inches)
    dxf_buffer = create_dxf_buffer(width, length, flange_length, add_kickout, st.session_state.holes, st.session_state.project_name)
    
    st.download_button(
        label="Download DXF (R2000, inches)",
        data=dxf_buffer,
        file_name=f"{st.session_state.project_name or 'chase_cover'}.dxf",
        mime="application/dxf"
    )

    if st.session_state.uploaded_files_data:
        st.subheader("Uploaded Photos")
        for name, data in st.session_state.uploaded_files_data:
            data.seek(0)  # Reset buffer for display
            image = Image.open(data)
            st.image(image, caption=name, use_container_width=True)

    # Email Export with SMTP
    st.subheader("Export Data")
    if st.button("Send to Shop"):
        try:
            sender_email = os.getenv("SENDER_EMAIL")
            sender_password = os.getenv("SENDER_PASSWORD")
            recipient_email = "mark@primeroofingfl.com"
            if not sender_email or not sender_password:
                raise ValueError("Email credentials not set in environment variables.")
            
            msg = MIMEMultipart()
            msg["From"] = sender_email
            msg["To"] = recipient_email
            msg["Subject"] = f"Chimney Cap Measurements - {st.session_state.project_name or 'Unnamed Project'}"
            
            body = "Chase Cover Measurements:\n\n"
            body += f"Project Name: {st.session_state.project_name or 'Unnamed Project'}\n"
            body += f"Length (Front to Back): {length:.1f} inches\n"
            body += f"Width (Left to Right): {width:.1f} inches\n"
            body += f"Outer flange length (turndown): {flange_length:.1f} inches\n"
            body += f"Add Kickout: {add_kickout}\n"
            body += f"Color: {st.session_state.color}"
            if st.session_state.color == "Other":
                body += f" ({st.session_state.custom_color})\n"
            else:
                body += "\n"
            body += f"Spark Arrestor: {st.session_state.spark_arrestor}"
            if st.session_state.spark_arrestor:
                body += f" - Details: {st.session_state.spark_details}\n"
            else:
                body += "\n"
            body += f"Windband: {st.session_state.windband}\n"
            body += "Holes:\n"
            for i, hole in enumerate(st.session_state.holes):
                body += f"  Hole {i+1}: Diameter={hole['diameter']:.1f} inches, Collar Height={hole['collar_height']:.1f} inches\n"
                for side, dist in hole['distances'].items():
                    body += f"    Distance from {side.capitalize()}: {dist:.1f} inches\n"
            body += f"Additional Notes: {st.session_state.additional_notes or 'None'}\n"
            msg.attach(MIMEText(body, "plain"))
            
            # Attach photos
            for name, data in st.session_state.uploaded_files_data:
                data.seek(0)  # Reset buffer for attachment
                attachment = MIMEApplication(data.read(), _subtype="png")
                attachment.add_header("Content-Disposition", "attachment", filename=name)
                msg.attach(attachment)
            
            # Attach JPG
            st.session_state.jpg_buffer.seek(0)
            jpg_attachment = MIMEApplication(st.session_state.jpg_buffer.read(), _subtype="jpg")
            jpg_attachment.add_header("Content-Disposition", "attachment", filename=f"{st.session_state.project_name or 'chase_cover'}_sketch.jpg")
            msg.attach(jpg_attachment)
            
            # Attach DXF (R2000, inches)
            dxf_buffer.seek(0)
            attachment = MIMEApplication(dxf_buffer.read(), _subtype="dxf")
            attachment.add_header("Content-Disposition", "attachment", filename=f"{st.session_state.project_name or 'chase_cover'}.dxf")
            msg.attach(attachment)
            
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
            st.success("Data, photos, JPG, and DXF sent to Prime Roofing Shop")
        except Exception as e:
            st.error(f"Failed to send email: {e}")

st.sidebar.header("Instructions")
st.sidebar.write("""
1. Enter the measurements and number of holes.
2. Enter hole details (at least 3 distances per hole).
3. Add notes and upload photos.
4. Click 'Create Sketch' to see the 2D sketch.
5. Click 'Send to Shop' to send data, photos, and DXF to the shop.
""")