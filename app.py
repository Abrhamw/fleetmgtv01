import streamlit as st
import pandas as pd
import sqlite3
import seaborn as sns
import matplotlib.pyplot as plt
from datetime import datetime, date, timedelta
import os
import hashlib
import pathlib
import matplotlib.dates as mdates
from io import BytesIO
import folium
from streamlit_folium import folium_static
import time

# Get current directory
DATA_DIR = st.session_state.get("data_dir", os.path.join(os.getcwd(), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'fleet.db')

# Database setup
def initialize_database():
    """Create database tables if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vehicle (
        plate_number TEXT PRIMARY KEY,
        chasis TEXT UNIQUE NOT NULL,
        vehicle_type TEXT,
        make TEXT,
        model TEXT,
        year TEXT,
        fuel_type TEXT,
        fuel_capacity REAL,
        fuel_consumption REAL,
        loading_capacity TEXT,
        assigned_for TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS driver (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        id_number TEXT UNIQUE,
        phone TEXT,
        reporting_to TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS compliance (
        plate_number TEXT PRIMARY KEY,
        insurance_type TEXT,
        insurance_date TEXT,
        yearly_inspection TEXT,
        inspection_date TEXT,
        safety_audit TEXT,
        utilization_history TEXT,
        accident_history TEXT,
        FOREIGN KEY(plate_number) REFERENCES vehicle(plate_number)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS maintenance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plate_number TEXT,
        last_service_km INTEGER,
        last_service_date TEXT,
        next_service_km INTEGER,
        next_service_date TEXT,
        maintenance_center TEXT,
        FOREIGN KEY(plate_number) REFERENCES vehicle(plate_number)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS assignment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plate_number TEXT,
        driver_id INTEGER,
        work_place TEXT,
        start_date TEXT,
        end_date TEXT,
        gps_position TEXT,
        geofence_violations INTEGER,
        last_update TEXT,
        FOREIGN KEY(plate_number) REFERENCES vehicle(plate_number),
        FOREIGN KEY(driver_id) REFERENCES driver(id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user'
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        change_type TEXT NOT NULL,
        table_name TEXT NOT NULL,
        record_id TEXT NOT NULL,
        change_time TEXT NOT NULL
    )''')
    
    # Create default admin user if doesn't exist
    hashed = hashlib.sha256('admin123'.encode()).hexdigest()
    cursor.execute('''
        INSERT OR IGNORE INTO users (username, password, role)
        VALUES (?, ?, ?)
    ''', ('admin', hashed, 'admin'))
    
    conn.commit()
    conn.close()

# Initialize database on startup
initialize_database()

# Enums
VEHICLE_TYPES = ('Pickup', 'Land Cruiser', 'Prado', 'V8', 'Hardtop', 'Minibus', 'Bus', 'Crane', 'ISUZU FSR', 'Other')
FUEL_TYPES = ('Diesel', 'Benzin', 'Hybrid', 'Electric')
ASSIGNMENT_TYPES = ('Program Office I', 'Program Office II', 'Program Office III', 'Program Office IV', 
                    'Central I Region', 'Central II Region', 'Central III Region','North Region',
                    'North East I Region','North East II Region','North West Region','West Region',
                    'South West Region','South I Region','South II Region','East I Region',
                    'East II Region','Region Coordination Office', 'Load Dispatch Center', 'Other')
INSURANCE_TYPES = ('Fully Insured', 'Partial')
SAFETY_TYPES = ('Safe', 'Fair', 'Not Safe')
MAINTENANCE_CENTERS = ('EEP', 'Moenco', 'Other')
YES_NO = ('Yes', 'No')

# User Authentication
def create_user(username, password, role='user'):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    hashed = hashlib.sha256(password.encode()).hexdigest()
    try:
        cursor.execute('INSERT INTO users VALUES (?, ?, ?)', (username, hashed, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # User already exists
    finally:
        conn.close()

def verify_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    hashed = hashlib.sha256(password.encode()).hexdigest()
    cursor.execute('SELECT * FROM users WHERE username=? AND password=?', (username, hashed))
    result = cursor.fetchone()
    conn.close()
    return result if result else None

def get_user_role(username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE username=?', (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None
def view_change_log():
    st.title("Change Log")
    try:
        conn = sqlite3.connect(DB_PATH)
        log = pd.read_sql("SELECT * FROM change_log ORDER BY change_time DESC", conn)
        conn.close()
        
        if not log.empty:
            st.dataframe(log)
        else:
            st.info("No changes logged yet")
    except Exception as e:
        st.error(f"Database error: {str(e)}")
# New function to log changes
def log_change(change_type, table_name, record_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO change_log (username, change_type, table_name, record_id, change_time)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        st.session_state.username,
        change_type,
        table_name,
        str(record_id),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ))
    conn.commit()
    conn.close()

# Dashboard functions
def get_dashboard_counts():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM vehicle")
    vehicle_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM driver")
    driver_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM assignment WHERE end_date IS NULL OR end_date >= date('now')")
    assignment_count = cursor.fetchone()[0]

    cursor.execute('''
        SELECT v.plate_number, v.make, v.model, m.next_service_date, m.maintenance_center
        FROM maintenance m
        JOIN vehicle v ON m.plate_number = v.plate_number
        WHERE DATE(m.next_service_date) <= DATE('now', '+7 days')
        ORDER BY DATE(m.next_service_date)
        LIMIT 5
    ''')
    maintenance_due = cursor.fetchall()

    cursor.execute('''
        SELECT v.plate_number, v.make, v.model,
               CASE
                   WHEN c.yearly_inspection = 'No' THEN 'Inspection Missing'
                   WHEN DATE(c.inspection_date) < DATE('now', '-1 year') THEN 'Inspection Expired'
                   WHEN DATE(c.insurance_date) < DATE('now', '-1 year') THEN 'Insurance Expired'
                   ELSE 'Unknown Issue'
               END AS issue_type
        FROM compliance c
        JOIN vehicle v ON c.plate_number = v.plate_number
        WHERE c.yearly_inspection = 'No'
            OR DATE(c.inspection_date) < DATE('now', '-1 year')
            OR DATE(c.insurance_date) < DATE('now', '-1 year')
        LIMIT 5
    ''')
    compliance_issues = cursor.fetchall()

    conn.close()
    return vehicle_count, driver_count, assignment_count, maintenance_due, compliance_issues

def show_dashboard():
    try:
        counts = get_dashboard_counts()
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        return
    
    st.subheader("Dashboard Overview")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Vehicles", counts[0])
    col2.metric("Total Drivers", counts[1])
    col3.metric("Active Assignments", counts[2])
    
    st.divider()
    
    # Maintenance Due
    st.subheader("Upcoming Maintenance (Next 7 Days)")
    if counts[3]:
        df_maintenance = pd.DataFrame(counts[3], columns=["Plate", "Make", "Model", "Next Service", "Center"])
        st.dataframe(df_maintenance)
        
        # Visualization
        if len(df_maintenance) > 0:
            fig, ax = plt.subplots()
            sns.countplot(data=df_maintenance, x='Center', ax=ax)
            plt.title('Maintenance Centers')
            st.pyplot(fig)
    else:
        st.info("No maintenance due in next 7 days")
    
    st.divider()
    
    # Compliance Issues
    st.subheader("Compliance Issues")
    if counts[4]:
        df_compliance = pd.DataFrame(counts[4], columns=["Plate", "Make", "Model", "Issue"])
        st.dataframe(df_compliance)
        
        # Visualization
        if len(df_compliance) > 0:
            fig, ax = plt.subplots()
            df_compliance['Issue'].value_counts().plot.pie(autopct='%1.1f%%', ax=ax)
            plt.title('Compliance Issue Distribution')
            st.pyplot(fig)
    else:
        st.info("No compliance issues found")

# Vehicle Management
def manage_vehicles():
    st.title("Vehicle Management")
    
    # Add new vehicle
    with st.expander("Add New Vehicle", expanded=False):
        with st.form("vehicle_form", clear_on_submit=True):
            plate = st.text_input("Plate Number*").upper().strip()
            chasis = st.text_input("Chasis Number*")
            col1, col2 = st.columns(2)
            vehicle_type = col1.selectbox("Type", VEHICLE_TYPES)
            fuel_type = col2.selectbox("Fuel Type", FUEL_TYPES)
            make = st.text_input("Make")
            model = st.text_input("Model")
            year = st.text_input("Year")
            fuel_capacity = st.number_input("Fuel Capacity", min_value=0.0, format="%.2f", value=0.0)
            fuel_consumption = st.number_input("Fuel Consumption", min_value=0.0, format="%.2f", value=0.0)
            loading_capacity = st.text_input("Loading Capacity")
            assigned_for = st.selectbox("Assigned For", ASSIGNMENT_TYPES)
            
            submitted = st.form_submit_button("Add Vehicle")
            if submitted:
                if plate and chasis:
                    try:
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO vehicle (
                                plate_number, chasis, vehicle_type, make, model, year, 
                                fuel_type, fuel_capacity, fuel_consumption, 
                                loading_capacity, assigned_for
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            plate, chasis, vehicle_type, make, model, year, 
                            fuel_type, fuel_capacity, fuel_consumption, 
                            loading_capacity, assigned_for
                        ))
                        conn.commit()
                        log_change("INSERT", "vehicle", plate)
                        st.success("Vehicle added successfully!")
                    except sqlite3.IntegrityError:
                        st.error("Plate number or chasis already exists!")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                    finally:
                        conn.close()
                else:
                    st.error("Plate and Chasis are required fields")

    # View and edit vehicles
    st.subheader("Existing Vehicles")
    try:
        conn = sqlite3.connect(DB_PATH)
        vehicles = pd.read_sql("SELECT * FROM vehicle", conn)
        conn.close()
        
        if not vehicles.empty:
            # Add delete functionality
            st.dataframe(vehicles)
            
            # Visualization
            st.subheader("Vehicle Distribution")
            col1, col2 = st.columns(2)
            with col1:
                if not vehicles.empty and 'vehicle_type' in vehicles:
                    fig, ax = plt.subplots()
                    sns.countplot(data=vehicles, x='vehicle_type', ax=ax)
                    plt.xticks(rotation=45)
                    plt.title('By Vehicle Type')
                    st.pyplot(fig)
            
            with col2:
                if not vehicles.empty and 'assigned_for' in vehicles:
                    fig, ax = plt.subplots()
                    sns.countplot(data=vehicles, x='assigned_for', ax=ax)
                    plt.xticks(rotation=90)
                    plt.title('By Assignment Type')
                    st.pyplot(fig)
        else:
            st.info("No vehicles found in database")
    except Exception as e:
        st.error(f"Database error: {str(e)}")

# Driver Management
def manage_drivers():
    st.title("Driver Management")
    
    # Add new driver
    with st.expander("Add New Driver", expanded=False):
        with st.form("driver_form", clear_on_submit=True):
            name = st.text_input("Full Name*")
            id_number = st.text_input("ID Number*")
            phone = st.text_input("Phone Number")
            reporting_to = st.selectbox("Reporting To", ASSIGNMENT_TYPES)
            
            submitted = st.form_submit_button("Add Driver")
            if submitted:
                if name and id_number:
                    try:
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO driver (name, id_number, phone, reporting_to)
                            VALUES (?, ?, ?, ?)
                        ''', (name, id_number, phone, reporting_to))
                        conn.commit()
                        st.success("Driver added successfully!")
                    except sqlite3.IntegrityError:
                        st.error("ID number already exists!")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                    finally:
                        conn.close()
                else:
                    st.error("Name and ID Number are required fields")

    # View and manage drivers
    st.subheader("Existing Drivers")
    try:
        conn = sqlite3.connect(DB_PATH)
        drivers = pd.read_sql("SELECT * FROM driver", conn)
        conn.close()
        
        if not drivers.empty:
            st.dataframe(drivers)
            
            # Visualization
            st.subheader("Driver Distribution")
            if not drivers.empty and 'reporting_to' in drivers:
                fig, ax = plt.subplots()
                drivers['reporting_to'].value_counts().plot.bar(ax=ax)
                plt.xticks(rotation=90)
                plt.title('Drivers by Reporting To')
                st.pyplot(fig)
        else:
            st.info("No drivers found in database")
    except Exception as e:
        st.error(f"Database error: {str(e)}")

# Assignment Management
def manage_assignments():
    st.title("Assignment Management")
    
    # Get vehicles and drivers for dropdowns
    conn = sqlite3.connect(DB_PATH)
    vehicles = pd.read_sql("SELECT plate_number FROM vehicle", conn)
    drivers = pd.read_sql("SELECT id, name FROM driver", conn)
    conn.close()
    
    # Add new assignment
    with st.expander("Create New Assignment", expanded=False):
        with st.form("assignment_form", clear_on_submit=True):
            plate_number = st.selectbox("Vehicle*", vehicles['plate_number'])
            driver_id = st.selectbox("Driver*", drivers['id'], format_func=lambda x: f"{x} - {drivers.loc[drivers['id'] == x, 'name'].values[0]}")
            work_place = st.selectbox("Work Place", ASSIGNMENT_TYPES)
            col1, col2 = st.columns(2)
            start_date = col1.date_input("Start Date*", value=date.today())
            end_date = col2.date_input("End Date (optional)", value=None)
            gps_position = st.text_input("GPS Position (lat,lon)")
            geofence_violations = st.number_input("Geofence Violations", min_value=0, value=0)
            
            submitted = st.form_submit_button("Create Assignment")
            if submitted:
                if plate_number and driver_id and start_date:
                    try:
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO assignment (
                                plate_number, driver_id, work_place, start_date, 
                                end_date, gps_position, geofence_violations, last_update
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            plate_number, driver_id, work_place, start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d') if end_date else None,
                            gps_position, geofence_violations, datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                        conn.commit()
                        st.success("Assignment created successfully!")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                    finally:
                        conn.close()
                else:
                    st.error("Vehicle, Driver, and Start Date are required fields")

    # View and manage assignments
    st.subheader("Current Assignments")
    try:
        conn = sqlite3.connect(DB_PATH)
        assignments = pd.read_sql('''
            SELECT a.id, v.plate_number, v.vehicle_type, d.name AS driver_name, 
                   a.work_place, a.start_date, a.end_date, a.geofence_violations,
                   a.gps_position, a.last_update
            FROM assignment a
            JOIN vehicle v ON a.plate_number = v.plate_number
            JOIN driver d ON a.driver_id = d.id
            WHERE a.end_date IS NULL OR a.end_date >= date('now')
        ''', conn)
        conn.close()
        
        if not assignments.empty:
            st.dataframe(assignments)
            
            # Visualization
            st.subheader("Assignment Distribution")
            col1, col2 = st.columns(2)
            with col1:
                if not assignments.empty and 'work_place' in assignments:
                    fig, ax = plt.subplots()
                    assignments['work_place'].value_counts().plot.bar(ax=ax)
                    plt.xticks(rotation=90)
                    plt.title('Assignments by Work Place')
                    st.pyplot(fig)
            
            with col2:
                if not assignments.empty and 'vehicle_type' in assignments:
                    fig, ax = plt.subplots()
                    assignments['vehicle_type'].value_counts().plot.pie(autopct='%1.1f%%', ax=ax)
                    plt.title('Vehicle Types in Assignments')
                    st.pyplot(fig)
        else:
            st.info("No active assignments found")
    except Exception as e:
        st.error(f"Database error: {str(e)}")
    # In manage_assignments() function
    gps_position = st.text_input("GPS Position (lat,lon)")
    if gps_position:
        try:
            lat, lon = map(float, gps_position.split(','))
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                st.error("Invalid GPS coordinates. Latitude must be between -90 and 90, Longitude between -180 and 180")
        except ValueError:
            st.error("Invalid GPS format. Use 'latitude,longitude' (e.g., 9.145,40.4897)")
# Compliance Management
def manage_compliance():
    st.title("Compliance Management")
    
    # Get vehicles for dropdown
    conn = sqlite3.connect(DB_PATH)
    vehicles = pd.read_sql("SELECT plate_number FROM vehicle", conn)
    conn.close()
    
    if vehicles.empty:
        st.warning("No vehicles found in database")
        return
    
    # Select vehicle
    plate_number = st.selectbox("Select Vehicle", vehicles['plate_number'])
    
    if not plate_number:
        st.warning("Please select a vehicle")
        return
    
    # Get existing compliance data
    conn = sqlite3.connect(DB_PATH)
    compliance = pd.read_sql(f"SELECT * FROM compliance WHERE plate_number = '{plate_number}'", conn)
    conn.close()
    
    # Form for compliance data
    with st.form("compliance_form"):
        # Set default values if compliance data exists
        insurance_default = compliance.iloc[0]['insurance_type'] if not compliance.empty else INSURANCE_TYPES[0]
        yearly_default = compliance.iloc[0]['yearly_inspection'] if not compliance.empty else YES_NO[0]
        safety_default = compliance.iloc[0]['safety_audit'] if not compliance.empty else SAFETY_TYPES[0]
        
        insurance_type = st.selectbox("Insurance Type", INSURANCE_TYPES, index=INSURANCE_TYPES.index(insurance_default) if not compliance.empty else 0)
        
        # Handle dates
        insurance_date_value = pd.to_datetime(compliance.iloc[0]['insurance_date']).date() if not compliance.empty and compliance.iloc[0]['insurance_date'] else date.today()
        inspection_date_value = pd.to_datetime(compliance.iloc[0]['inspection_date']).date() if not compliance.empty and compliance.iloc[0]['inspection_date'] else date.today()
        
        insurance_date = st.date_input("Insurance Date", value=insurance_date_value)
        yearly_inspection = st.selectbox("Yearly Inspection", YES_NO, index=YES_NO.index(yearly_default) if not compliance.empty else 0)
        inspection_date = st.date_input("Inspection Date", value=inspection_date_value)
        safety_audit = st.selectbox("Safety Audit", SAFETY_TYPES, index=SAFETY_TYPES.index(safety_default) if not compliance.empty else 0)
        utilization_history = st.text_area("Utilization History", value="" if compliance.empty else compliance.iloc[0]['utilization_history'])
        accident_history = st.text_area("Accident History", value="" if compliance.empty else compliance.iloc[0]['accident_history'])
        
        submitted = st.form_submit_button("Save Compliance Data")
        if submitted:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                if compliance.empty:
                    # Insert new record
                    cursor.execute('''
                        INSERT INTO compliance (
                            plate_number, insurance_type, insurance_date, yearly_inspection, 
                            inspection_date, safety_audit, utilization_history, accident_history
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        plate_number, insurance_type, insurance_date.strftime('%Y-%m-%d'), 
                        # Change this line in the INSERT operation:
                          # Was '%Y-%m%d' which is incorrect
                        yearly_inspection, inspection_date.strftime('%Y-%m-%d'), 
                        safety_audit, utilization_history, accident_history
                    ))
                else:
                    # Update existing record
                    cursor.execute('''
                        UPDATE compliance SET
                            insurance_type = ?,
                            insurance_date = ?,
                            yearly_inspection = ?,
                            inspection_date = ?,
                            safety_audit = ?,
                            utilization_history = ?,
                            accident_history = ?
                        WHERE plate_number = ?
                    ''', (
                        insurance_type, insurance_date.strftime('%Y-%m-%d'), 
                        yearly_inspection, inspection_date.strftime('%Y-%m-%d'), 
                        safety_audit, utilization_history, accident_history, plate_number
                    ))
                conn.commit()
                st.success("Compliance data saved successfully!")
            except Exception as e:
                st.error(f"Error: {str(e)}")
            finally:
                conn.close()

# Maintenance Management
def manage_maintenance():
    st.title("Maintenance Management")
    
    # Get vehicles for dropdown
    conn = sqlite3.connect(DB_PATH)
    vehicles = pd.read_sql("SELECT plate_number FROM vehicle", conn)
    conn.close()
    
    if vehicles.empty:
        st.warning("No vehicles found in database")
        return
    
    # Select vehicle
    plate_number = st.selectbox("Select Vehicle", vehicles['plate_number'])
    
    if not plate_number:
        st.warning("Please select a vehicle")
        return
    
    # Add new maintenance record
    with st.expander("Add Maintenance Record", expanded=False):
        with st.form("maintenance_form", clear_on_submit=True):
            last_service_km = st.number_input("Last Service KM", min_value=0, value=0)
            last_service_date = st.date_input("Last Service Date", value=date.today())
            next_service_km = st.number_input("Next Service KM", min_value=0, value=0)
            next_service_date = st.date_input("Next Service Date", value=date.today() + timedelta(days=90))
            maintenance_center = st.selectbox("Maintenance Center", MAINTENANCE_CENTERS)
            
            submitted = st.form_submit_button("Add Record")
            if submitted:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO maintenance (
                            plate_number, last_service_km, last_service_date, 
                            next_service_km, next_service_date, maintenance_center
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        plate_number, last_service_km, last_service_date.strftime('%Y-%m-%d'),
                        next_service_km, next_service_date.strftime('%Y-%m-%d'), maintenance_center
                    ))
                    conn.commit()
                    st.success("Maintenance record added successfully!")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
                finally:
                    conn.close()

    # View maintenance history
    st.subheader("Maintenance History")
    try:
        conn = sqlite3.connect(DB_PATH)
        maintenance = pd.read_sql(f'''
            SELECT id, last_service_km, last_service_date, 
                   next_service_km, next_service_date, maintenance_center
            FROM maintenance
            WHERE plate_number = '{plate_number}'
            ORDER BY last_service_date DESC
        ''', conn)
        conn.close()
        
        if not maintenance.empty:
            st.dataframe(maintenance)
            
            # Visualization
            st.subheader("Service History")
            maintenance['last_service_date'] = pd.to_datetime(maintenance['last_service_date'])
            maintenance.sort_values('last_service_date', inplace=True)
            
            if len(maintenance) > 1:
                fig, ax = plt.subplots(figsize=(10, 4))
                ax.plot(maintenance['last_service_date'], maintenance['last_service_km'], 'o-', label='Service KM')
                ax.set_title('Service Kilometers Over Time')
                ax.set_xlabel('Service Date')
                ax.set_ylabel('Kilometers')
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
                plt.xticks(rotation=45)
                st.pyplot(fig)
            else:
                st.info("At least 2 records needed for visualization")
        else:
            st.info("No maintenance records found for this vehicle")
    except Exception as e:
        st.error(f"Database error: {str(e)}")

# Report Generation
def generate_reports():
    st.title("Report Generation")
    
    report_type = st.selectbox("Select Report Type", [
        "Assignment Summary",
        "Unassigned Vehicles",
        "Driver Assignments"
    ])
    
    if report_type == "Assignment Summary":
        st.subheader("Assignment Summary Report")
        try:
            conn = sqlite3.connect(DB_PATH)
            
            # Assignment counts by type
            assignment_counts = pd.read_sql('''
                SELECT assigned_for AS assignment_type, COUNT(*) AS vehicle_count
                FROM vehicle
                GROUP BY assigned_for
            ''', conn)
            
            # Driver counts by reporting to
            driver_counts = pd.read_sql('''
                SELECT reporting_to, COUNT(*) AS driver_count
                FROM driver
                GROUP BY reporting_to
            ''', conn)
            
            # Ongoing assignments
            ongoing_assignments = pd.read_sql('''
                SELECT COUNT(*) AS ongoing_count
                FROM assignment
                WHERE end_date IS NULL OR end_date >= date('now')
            ''', conn).iloc[0]['ongoing_count']
            
            # Unassigned vehicles
            unassigned_vehicles = pd.read_sql('''
                SELECT COUNT(*) AS unassigned_count
                FROM vehicle
                WHERE plate_number NOT IN (
                    SELECT plate_number
                    FROM assignment
                    WHERE end_date IS NULL OR end_date >= date('now')
                )
            ''', conn).iloc[0]['unassigned_count']
            
            conn.close()
            
            # Display metrics
            col1, col2 = st.columns(2)
            col1.metric("Ongoing Assignments", ongoing_assignments)
            col2.metric("Unassigned Vehicles", unassigned_vehicles)
            
            # Visualizations
            st.subheader("Vehicles by Assignment Type")
            if not assignment_counts.empty:
                fig, ax = plt.subplots()
                sns.barplot(data=assignment_counts, x='assignment_type', y='vehicle_count', ax=ax)
                plt.xticks(rotation=90)
                st.pyplot(fig)
            else:
                st.info("No assignment data available")
            
            st.subheader("Drivers by Reporting To")
            if not driver_counts.empty:
                fig, ax = plt.subplots()
                sns.barplot(data=driver_counts, x='reporting_to', y='driver_count', ax=ax)
                plt.xticks(rotation=90)
                st.pyplot(fig)
            else:
                st.info("No driver data available")
                
        except Exception as e:
            st.error(f"Database error: {str(e)}")
    
    elif report_type == "Unassigned Vehicles":
        st.subheader("Unassigned Vehicles Report")
        try:
            conn = sqlite3.connect(DB_PATH)
            unassigned = pd.read_sql('''
                SELECT v.*
                FROM vehicle v
                WHERE v.plate_number NOT IN (
                    SELECT a.plate_number
                    FROM assignment a
                    WHERE a.end_date IS NULL OR a.end_date >= date('now')
                )
            ''', conn)
            conn.close()
            
            if not unassigned.empty:
                st.dataframe(unassigned)
                
                # Export button
                if st.button("Export to Excel"):
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        unassigned.to_excel(writer, sheet_name='Unassigned Vehicles', index=False)
                    st.download_button(
                        label="Download Excel",
                        data=output.getvalue(),
                        file_name=f"unassigned_vehicles_{date.today()}.xlsx",
                        mime="application/vnd.ms-excel"
                    )
            else:
                st.info("All vehicles are currently assigned")
                
        except Exception as e:
            st.error(f"Database error: {str(e)}")
    
    elif report_type == "Driver Assignments":
        st.subheader("Driver Assignments Report")
        try:
            conn = sqlite3.connect(DB_PATH)
            assignments = pd.read_sql('''
                SELECT d.name, d.id_number, d.phone, d.reporting_to,
                       v.plate_number, v.vehicle_type, a.work_place,
                       a.start_date, a.end_date
                FROM driver d
                LEFT JOIN assignment a ON d.id = a.driver_id
                LEFT JOIN vehicle v ON a.plate_number = v.plate_number
                WHERE a.end_date IS NULL OR a.end_date >= date('now')
            ''', conn)
            conn.close()
            
            if not assignments.empty:
                st.dataframe(assignments)
                
                # Export button
                if st.button("Export to Excel"):
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        assignments.to_excel(writer, sheet_name='Driver Assignments', index=False)
                    st.download_button(
                        label="Download Excel",
                        data=output.getvalue(),
                        file_name=f"driver_assignments_{date.today()}.xlsx",
                        mime="application/vnd.ms-excel"
                    )
            else:
                st.info("No active assignments found")
                
        except Exception as e:
            st.error(f"Database error: {str(e)}")

# NEW: Real-time GPS Tracking
def realtime_gps_tracking():
    st.title("Real-time Vehicle Tracking")
    
    # Get active assignments with GPS positions
    conn = sqlite3.connect(DB_PATH)
    query = '''
        SELECT a.id, v.plate_number, v.vehicle_type, d.name AS driver_name, 
               a.work_place, a.gps_position, a.last_update
        FROM assignment a
        JOIN vehicle v ON a.plate_number = v.plate_number
        JOIN driver d ON a.driver_id = d.id
        WHERE a.end_date IS NULL 
            OR a.end_date >= date('now')
            AND a.gps_position IS NOT NULL
    '''
    assignments = pd.read_sql(query, conn)
    conn.close()
    
    if assignments.empty:
        st.warning("No active assignments with GPS data found")
        return
    
    # Create map
    st.subheader("Vehicle Locations")
    map_center = [9.145, 40.4897]  # Center of Ethiopia
    m = folium.Map(location=map_center, zoom_start=6)
    
    # Add markers
    for _, row in assignments.iterrows():
        if row['gps_position']:
            try:
                lat, lon = map(float, row['gps_position'].split(','))
                popup = f"{row['plate_number']}<br>{row['driver_name']}<br>{row['work_place']}"
                folium.Marker(
                    [lat, lon],
                    popup=popup,
                    tooltip=f"{row['vehicle_type']} - {row['driver_name']}"
                ).add_to(m)
            except:
                continue
    
    # Display map
    folium_static(m)
    
    # Update button
    if st.button("Refresh Locations"):
        st.rerun()
    
    # Display table
    st.subheader("Assignment Details")
    st.dataframe(assignments[['plate_number', 'driver_name', 'work_place', 'last_update']])

# NEW: One-page summary
def vehicle_driver_summary():
    st.title("Vehicle & Driver Summary")
    
    search_type = st.radio("Search by:", ["Vehicle Plate", "Driver ID"])
    
    if search_type == "Vehicle Plate":
        plate = st.text_input("Enter Vehicle Plate Number").upper().strip()
        if plate:
            try:
                conn = sqlite3.connect(DB_PATH)
                
                # Vehicle details
                vehicle = pd.read_sql(f"SELECT * FROM vehicle WHERE plate_number = '{plate}'", conn)
                if vehicle.empty:
                    st.warning("Vehicle not found")
                    return
                
                st.subheader("Vehicle Details")
                st.dataframe(vehicle)
                
                # Compliance
                compliance = pd.read_sql(f"SELECT * FROM compliance WHERE plate_number = '{plate}'", conn)
                st.subheader("Compliance")
                if not compliance.empty:
                    st.dataframe(compliance)
                else:
                    st.info("No compliance records")
                
                # Maintenance
                maintenance = pd.read_sql(f"SELECT * FROM maintenance WHERE plate_number = '{plate}' ORDER BY last_service_date DESC", conn)
                st.subheader("Maintenance History")
                if not maintenance.empty:
                    st.dataframe(maintenance)
                else:
                    st.info("No maintenance records")
                
                # Assignments
                assignments = pd.read_sql(f'''
                    SELECT a.start_date, a.end_date, d.name AS driver_name, 
                           d.id_number, d.phone, a.work_place
                    FROM assignment a
                    JOIN driver d ON a.driver_id = d.id
                    WHERE a.plate_number = '{plate}'
                    ORDER BY a.start_date DESC
                ''', conn)
                st.subheader("Assignment History")
                if not assignments.empty:
                    st.dataframe(assignments)
                else:
                    st.info("No assignment records")
                
                conn.close()
                
            except Exception as e:
                st.error(f"Database error: {str(e)}")
    
    else:  # Driver ID
        driver_id = st.text_input("Enter Driver ID")
        if driver_id:
            try:
                conn = sqlite3.connect(DB_PATH)
                
                # Driver details
                driver = pd.read_sql(f"SELECT * FROM driver WHERE id = '{driver_id}'", conn)
                if driver.empty:
                    st.warning("Driver not found")
                    return
                
                st.subheader("Driver Details")
                st.dataframe(driver)
                
                # Current assignment
                current_assignment = pd.read_sql(f'''
                    SELECT a.start_date, a.end_date, v.plate_number, 
                           v.vehicle_type, v.make, v.model, a.work_place
                    FROM assignment a
                    JOIN vehicle v ON a.plate_number = v.plate_number
                    WHERE a.driver_id = '{driver_id}'
                        AND (a.end_date IS NULL OR a.end_date >= date('now'))
                ''', conn)
                st.subheader("Current Assignment")
                if not current_assignment.empty:
                    st.dataframe(current_assignment)
                else:
                    st.info("No current assignment")
                
                # Assignment history
                assignment_history = pd.read_sql(f'''
                    SELECT a.start_date, a.end_date, v.plate_number, 
                           v.vehicle_type, v.make, v.model, a.work_place
                    FROM assignment a
                    JOIN vehicle v ON a.plate_number = v.plate_number
                    WHERE a.driver_id = '{driver_id}'
                    ORDER BY a.start_date DESC
                ''', conn)
                st.subheader("Assignment History")
                if not assignment_history.empty:
                    st.dataframe(assignment_history)
                else:
                    st.info("No assignment history")
                
                conn.close()
                
            except Exception as e:
                st.error(f"Database error: {str(e)}")

# NEW: User management
def manage_users():
    st.title("User Management")
    
    # Only admin can access
    if st.session_state.get("role") != "admin":
        st.warning("Only administrators can access this page")
        return
    
    # Create new user
    with st.expander("Create New User", expanded=True):
        with st.form("user_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            role = st.selectbox("Role", ["user", "admin"])
            
            if st.form_submit_button("Create User"):
                if username and password:
                    if create_user(username, password, role):
                        st.success("User created successfully!")
                    else:
                        st.error("Username already exists")
                else:
                    st.error("Username and password are required")
    
    # View existing users
    st.subheader("Existing Users")
    try:
        conn = sqlite3.connect(DB_PATH)
        users = pd.read_sql("SELECT username, role FROM users", conn)
        conn.close()
        
        if not users.empty:
            st.dataframe(users)
        else:
            st.info("No users found")
    except Exception as e:
        st.error(f"Database error: {str(e)}")

def login_sidebar():
    st.sidebar.title("Fleet Management System")
    
    # Check if user is already logged in
    if st.session_state.get("logged_in"):
        st.sidebar.subheader(f"Welcome, {st.session_state.username}")
        st.sidebar.write(f"Role: {st.session_state.get('role', 'user')}")
        if st.session_state.get("role") == "admin":
            st.sidebar.divider()
            st.sidebar.caption(f"Database location: `{DB_PATH}`")
        return True
    
    # Only show login form if not logged in
    st.sidebar.subheader("Login")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Login"):
        user = verify_user(username, password)
        if user:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.role = get_user_role(username)
            st.sidebar.success("Logged in successfully!")
            st.rerun()
        else:
            st.sidebar.error("Invalid credentials")
    
    return False
    # Main App
def main():
    st.set_page_config(
        page_title="Fleet Management System",
        page_icon="🚚",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    # Add at top after imports
    st.markdown("""
    <style>
    @media (max-width: 768px) {
        .block-container {
            padding: 1rem !important;
        }
        .stDataFrame {
            width: 100% !important;
        }
        .column-css {
            flex-direction: column !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)


    # Navigation
    nav_options = [
        "Dashboard",
        "Manage Vehicles",
        "Manage Drivers",
        "Manage Assignments",
        "Manage Compliance",
        "Manage Maintenance",
        "Reports",
        "GPS Tracking",
        "Summary Lookup",
    ]
    
    if st.session_state.get("role") == "admin":
        nav_options.append("Change Log")
        nav_options.append("User Management")
    
    nav_options.append("Logout")
    
    app_mode = st.sidebar.selectbox("Navigation", nav_options)
    
    st.sidebar.divider()
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.pop("username", None)
        st.session_state.pop("role", None)
        st.rerun()
    
    # Page routing
    if app_mode == "Dashboard":
        show_dashboard()
    elif app_mode == "Manage Vehicles":
        manage_vehicles()
    elif app_mode == "Manage Drivers":
        manage_drivers()
    elif app_mode == "Manage Assignments":
        manage_assignments()
    elif app_mode == "Manage Compliance":
        manage_compliance()
    elif app_mode == "Manage Maintenance":
        manage_maintenance()
    elif app_mode == "Reports":
        generate_reports()
    elif app_mode == "GPS Tracking":
        realtime_gps_tracking()
    elif app_mode == "Summary Lookup":
        vehicle_driver_summary()
    elif app_mode == "User Management":
        manage_users()
    elif app_mode == "Change Log":
        view_change_log()
    elif app_mode == "Logout":
        st.session_state.logged_in = False
        st.rerun()

if __name__ == "__main__":
    main()
