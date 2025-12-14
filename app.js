// Firebase configuration
import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js';
import { getDatabase, ref, onValue } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-database.js';

const firebaseConfig = {
    databaseURL: "https://metrometrics-makehathon-default-rtdb.europe-west1.firebasedatabase.app/"
};

const app = initializeApp(firebaseConfig);
const database = getDatabase(app);

let metroData = null;
let allStations = [];
let currentStation = null; // Track currently displayed station
let occupancyPercentage = 50; // Default prototype value

// Line color mapping
const lineColors = {
    'Azul': '#0066cc',
    'Verde': '#00a550',
    'Vermelha': '#e3000b',
    'Amarela': '#ffcc00'
};

// Calculate color from green (0%) to red (100%) for occupancy, ensuring contrast for white text
function getOccupancyColor(percentage) {
    // Clamp between 0 and 100
    const p = Math.min(Math.max(percentage, 0), 100) / 100;
    // Green to yellow to red: 0% (0,180,0), 50% (255,180,0), 100% (255,0,0)
    let r, g, b;
    if (p < 0.5) {
        // Green (#00b400) to Yellow (#ffb400)
        // Segment: 0-50%: (r: 0->255, g:180, b:0)
        r = Math.round(0 + 255 * (p / 0.5));
        g = 180;
        b = 0;
    } else {
        // Yellow (#ffb400) to Red (#ff0000)
        // Segment: 50-100%: (r:255, g:180->0, b:0)
        r = 255;
        g = Math.round(180 * (1 - (p - 0.5) / 0.5));
        b = 0;
    }
    return `rgb(${r},${g},${b})`;
}

// Initialize
function init() {
    const dataRef = ref(database, '/');
    
    onValue(dataRef, (snapshot) => {
        const data = snapshot.val();
        if (data) {
            metroData = data;
            allStations = Object.keys(data.current_wait_times || {}).sort();
            updateLastUpdate(data.timestamp);
            
            // Get occupancy if available
            if (data.Occupancy !== undefined) {
                console.log(data.Occupancy);
                occupancyPercentage = data.Occupancy;
            }
            else {
                console.log("No occupancy data available");
            }
            
            // Auto-refresh currently displayed station or show station list
            if (currentStation) {
                displayStation(currentStation);
            } else {
                showStationList();
            }
        }
    });

    // Search functionality
    const searchInput = document.getElementById('searchInput');
    const suggestionsDiv = document.getElementById('suggestions');

    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        
        if (query === '') {
            suggestionsDiv.classList.remove('active');
            suggestionsDiv.innerHTML = '';
            return;
        }

        const filtered = allStations.filter(station => 
            station.toLowerCase().replace(/_/g, ' ').includes(query)
        );

        if (filtered.length > 0) {
            suggestionsDiv.innerHTML = filtered
                .map(station => `
                    <div class="suggestion-item" data-station="${station}">
                        ${station.replace(/_/g, ' ')}
                    </div>
                `)
                .join('');
            suggestionsDiv.classList.add('active');

            // Add click handlers
            document.querySelectorAll('.suggestion-item').forEach(item => {
                item.addEventListener('click', () => {
                    const stationName = item.dataset.station;
                    searchInput.value = stationName.replace(/_/g, ' ');
                    suggestionsDiv.classList.remove('active');
                    displayStation(stationName);
                });
            });
        } else {
            suggestionsDiv.innerHTML = '<div class="suggestion-item">No stations found</div>';
            suggestionsDiv.classList.add('active');
        }
    });

    // Close suggestions when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-container')) {
            suggestionsDiv.classList.remove('active');
        }
    });
}

function updateLastUpdate(timestamp) {
    const lastUpdateDiv = document.getElementById('lastUpdate');
    if (timestamp) {
        const date = new Date(timestamp);
        lastUpdateDiv.textContent = `Last update: ${date.toLocaleTimeString()}`;
    }
}

function showStationList() {
    const resultsDiv = document.getElementById('results');
    
    if (!metroData || !metroData.current_wait_times) {
        resultsDiv.innerHTML = '<div class="empty-state"><p>Loading stations...</p></div>';
        return;
    }
    
    let html = '<div class="station-list">';
    
    allStations.forEach(station => {
        const stationData = metroData.current_wait_times[station];
        const isClosed = stationData && stationData.NA === "NA";
        const lines = stationData && Object.keys(stationData).filter(k => k !== 'NA');
        
        html += `
            <div class="station-list-item ${isClosed ? 'closed' : ''}" onclick="selectStation('${station}')">
                <div class="station-list-name">${station.replace(/_/g, ' ')}</div>
                <div class="station-list-lines">
                    ${lines && lines.length > 0 ? lines.map(line => 
                        `<span class="line-badge" style="background-color: ${lineColors[line] || '#666'}">${line}</span>`
                    ).join('') : '<span class="closed-badge">Closed</span>'}
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    resultsDiv.innerHTML = html;
}

// Make selectStation available globally
window.selectStation = function(stationName) {
    document.getElementById('searchInput').value = stationName.replace(/_/g, ' ');
    displayStation(stationName);
};

function displayStation(stationName) {
    const resultsDiv = document.getElementById('results');
    
    // Store currently displayed station for auto-refresh
    currentStation = stationName;
    
    if (!metroData || !metroData.current_wait_times) {
        resultsDiv.innerHTML = '<div class="empty-state"><p>Loading data...</p></div>';
        return;
    }

    // Accept either underscored or spaced names
    const key = metroData.current_wait_times[stationName]
        ? stationName
        : stationName.replace(/ /g, '_');
    const stationData = metroData.current_wait_times[key];
    
    if (!stationData) {
        resultsDiv.innerHTML = '<div class="empty-state"><p>Station not found</p></div>';
        return;
    }

    // Check if station is closed (has NA key)
    if (stationData.NA === "NA") {
        resultsDiv.innerHTML = `
            <div class="station-card">
                <div class="station-name">${stationName.replace(/_/g, ' ')}</div>
                <div class="closed-message">Station is currently closed</div>
            </div>
        `;
        return;
    }

    // Check if station has no data (empty object) 
    if (Object.keys(stationData).length === 0) {
        resultsDiv.innerHTML = `
            <div class="station-card">
                <div class="station-name">${stationName.replace(/_/g, ' ')}</div>
                <div class="closed-message">No data available for this station</div>
            </div>
        `;
        return;
    }

    // Build HTML - iterate through lines
    let html = `
        <div class="station-card">
            <div class="station-name">
                <span class="back-button" onclick="window.goBack()">← Back</span>
                ${stationName.replace(/_/g, ' ')}
            </div>
    `;
    
    // Make goBack available globally
    window.goBack = function() {
        currentStation = null;
        showStationList();
    };

    let totalLines = 0;
    let totalDestinations = 0;

    // Structure is: station -> line -> destination -> wait_times
    for (const [lineName, destinations] of Object.entries(stationData)) {
        // Skip NA entries
        if (lineName === 'NA') continue;
        
        totalLines += 1;
        const lineColor = lineColors[lineName] || '#666';
        html += `<div class="line-card">`;
        html += `<div class="line-header ${lineName}" style="border-left-color: ${lineColor};">
            <div class="line-name" style="color: ${lineColor};">${lineName}</div>
        </div>`;
        
        // Check if this line has any destinations
        if (typeof destinations === 'object' && !Array.isArray(destinations)) {
            let hasData = false;
            
            for (const [destination, waitTimes] of Object.entries(destinations)) {
                if (Array.isArray(waitTimes) && waitTimes.length > 0) {
                    hasData = true;
                    totalDestinations += 1;
                    html += `<div class="destination">${destination.replace(/_/g, ' ')}</div>`;
                    html += '<div class="wait-times">';
                    
                    // Get valid times for darkness calculation
                    const validTimes = waitTimes.filter(t => typeof t === 'number' && t > 0);
                    const maxTime = validTimes.length > 0 ? Math.max(...validTimes) : 0;
                    
                    waitTimes.forEach(time => {
                        if (time === "--" || time === "NA") {
                            html += `<div class="wait-time wait-time-na">--</div>`;
                        } else if (typeof time === 'number' && time > 0) {
                            // Format as MM:SS
                            const minutes = Math.floor(time / 60);
                            const seconds = time % 60;
                            const formatted = `${minutes}:${seconds.toString().padStart(2, '0')}`;
                            
                            // Calculate darkness based on time (higher time = darker)
                            const darkness = maxTime > 0 ? (time / maxTime) * 0.7 : 0;
                            const darkerColor = `linear-gradient(rgba(0,0,0,${darkness}), rgba(0,0,0,${darkness})), ${lineColor}`;
                            
                            html += `<div class="wait-time" style="background: ${darkerColor}; color: #fff; border-color: ${lineColor};">${formatted}</div>`;
                        }
                    });
                    
                    html += '</div>';
                    
                    // Add train visualization
                    if (validTimes.length > 0) {
                        html += '<div class="train-line">';
                        html += `<div class="train-track" style="background-color: ${lineColor};"></div>`;
                        validTimes.forEach((time, index) => {
                            // Calculate position with padding (30px on each side = 60px total)
                            // Position from 5% to 95% to keep trains within bounds
                            const position = 5 + ((time / maxTime) * 90);
                            // Get occupancy color (green to red)
                            const occupancyColor = getOccupancyColor(occupancyPercentage);
                            html += `<div class="train-icon" style="left: ${position}%; background-color: ${occupancyColor};" title="Wait: ${Math.floor(time/60)}:${(time%60).toString().padStart(2, '0')} | Occupancy: ${occupancyPercentage}%">
                                <span class="train-occupancy">${occupancyPercentage}%</span>
                            </div>`;
                        });
                        html += '</div>';
                    }
                }
            }
            
            if (!hasData) {
                html += '<div class="no-data">No data available</div>';
            }
        } else {
            html += '<div class="no-data">No data available</div>';
        }
        
        html += '</div>';
    }

    html += '</div>';
    html += `<div class="debug-info">Lines: ${totalLines} · Destinations: ${totalDestinations}</div>`;
    resultsDiv.innerHTML = html;
}

// Initialize app
init();
