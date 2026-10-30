# Automatic Identification System (AIS) Overview

## 1. Executive Summary & Core Purpose

The **Automatic Identification System (AIS)** is an automated, broadcast-based maritime communication and tracking system. AIS continuously gathers and transmits key vessel data to allow maritime stakeholders (such as port authorities, naval commands, commercial operators, and coastal guards) to exchange navigational and identification details in real time.

### Key Benefits
* **Enhanced Maritime Safety:** Prevents collision through vessel-to-vessel visibility and supports Search and Rescue (SAR) operations.
* **Operational Efficiency:** Optimizes voyage planning, port arrivals, and anchorage management.
* **Maritime Domain Visibility:** Grants full situational awareness of global and regional naval traffic.

---

## 2. Technical Architecture & Transmission Mechanics

### How AIS Operates
1. **Onboard Equipment:** An AIS transceiver unit is integrated with the vessel's positioning equipment (e.g., GPS/GNSS) and navigational sensors.
2. **Signal Transmission:** Broadcasts data via **VHF (Very High Frequency)** radio frequencies (typically channels 87B/161.975 MHz and 88B/162.025 MHz) at regular, automated time intervals depending on vessel speed and maneuvering status.

### Signal Receivers & Architecture
AIS signals are picked up by several distinct ground and space-based nodes:

* **Nearby Vessels:** Enables immediate ship-to-ship collision avoidance.
* **Shore-Based AIS Base Stations:** Enables coastal surveillance within line-of-sight range (approx. 15–20 nautical miles).
* **Vessel Traffic Services (VTS) Centers:** Used for managing port congestion and coastal navigation corridors.
* **Satellite AIS (S-AIS):** Constellations of low-Earth orbit (LEO) satellites equipped with AIS receivers pick up signals from offshore and deep-ocean ships far beyond terrestrial antenna range.

$$
\text{Vessel AIS Transceiver} \xrightarrow{\text{VHF Radio}} \begin{cases} \text{Ship-to-Ship (Collision Avoidance)} \\ \text{Shore Stations / VTS (Coastal Traffic)} \\ \text{Satellite AIS / S-AIS (Offshore Surveillance)} \end{cases} \rightarrow \text{Real-Time Traffic Awareness}
$$

---

## 3. AIS Data Categories & System Identifiers

AIS payload data is broadly categorized into distinct structure types. While your initial notes highlight **Static Data**, complete AIS implementations process three main types:

### Data Categories
1. **Static Data:** Ship details set during installation (transmitted every 6 minutes or on request).
2. **Dynamic Data:** Automatically updating position and motion metrics (transmitted every 2 to 10 seconds while under way).
3. **Voyage-Related Data:** Information manually entered per voyage (transmitted every 6 minutes).

### Key Data Attributes & Unique Identifiers

| Attribute Field | Name | Category | Description |
| :--- | :--- | :--- | :--- |
| `ship_id` / `ais_ship_id` | Database ID | Internal | Primary key or software tracking index assigned within system databases. |
| `ship_name` | Vessel Name | Static | The officially registered name of the vessel. |
| `ship_mmsi` | MMSI | Static | **Maritime Mobile Service Identity**: A unique 9-digit radio identification number linked to the vessel's flag state and onboard communication equipment. |
| `ship_imo` | IMO Number | Static | **International Maritime Organization Number**: A permanent 7-to-9 digit unique identifier that remains with the hull forever, regardless of ownership, name, or flag changes. |

---

## 4. Enhanced Summary Table

| AIS Category | Frequency | Primary Attributes Included |
| :--- | :--- | :--- |
| **Static Information** | Every 6 min / On Request | MMSI, IMO Number, Vessel Name, Call Sign, Vessel Type, Dimensions (Length/Beam), GPS Antenna Location |
| **Dynamic Information** | 2–10 sec (under way)<br>3 min (at anchor) | Latitude, Longitude, Speed Over Ground (SOG), Course Over Ground (COG), Rate of Turn (ROT), Heading, Navigational Status |
| **Voyage Information** | Every 6 min | Draft depth, Hazardous Cargo Type, Destination, Estimated Time of Arrival (ETA) |