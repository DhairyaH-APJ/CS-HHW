const $ = (sel) => document.querySelector(sel);
const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let floors = []; // [{ floor_number, capacity, occupied, available, vehicles: [...] }]

// ---- API helper ------------------------------------------------------------
async function api(method, url, body) {
    const res = await fetch(url, {
        method,
        headers: body !== undefined ? { "Content-Type": "application/json" } : {},
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (res.status === 204) return null;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
        const d = data && data.detail;
        const message = Array.isArray(d) ? d.map((e) => `${e.loc.slice(-1)[0]}: ${e.msg}`).join("; ") : d || "Request failed";
        throw Object.assign(new Error(message), { status: res.status });
    }
    return data;
}

function showMsg(text, isError = false) {
    const el = $("#msg");
    el.textContent = text;
    el.className = isError ? "error" : "ok";
    el.hidden = false;
    clearTimeout(showMsg.t);
    showMsg.t = setTimeout(() => (el.hidden = true), 5000);
}

// ---- Load + render ---------------------------------------------------------
async function load() {
    try {
        const list = await api("GET", "/floors");
        await Promise.all(
            list.map(async (f) => (f.vehicles = await api("GET", `/floors/${f.floor_number}/vehicles`)))
        );
        floors = list;
        render();
    } catch (e) {
        showMsg(e.message, true);
    }
}

function render() {
    const cap = floors.reduce((s, f) => s + f.capacity, 0);
    const occ = floors.reduce((s, f) => s + f.occupied, 0);
    $("#summary").textContent = floors.length
        ? `${floors.length} floor(s) · ${occ} parked · ${cap - occ} spaces available of ${cap}`
        : "No floors yet. Add one to get started.";

    $("#floors").innerHTML = floors
        .map((f) => {
            const pct = Math.round((f.occupied / f.capacity) * 100);
            const rows = f.vehicles
                .map(
                    (v) => `<tr>
                        <td>${esc(v.number_plate)}</td><td>${esc(v.vehicle_type)}</td><td>${esc(v.colour)}</td>
                        <td>${esc(v.brand)}</td><td>${esc(v.model)}</td>
                        <td>${new Date(v.entered_at).toLocaleString()}</td>
                        <td class="row-actions">
                            <button data-action="edit-vehicle" data-plate="${esc(v.number_plate)}">Edit</button>
                            <button data-action="remove-vehicle" data-plate="${esc(v.number_plate)}">Remove</button>
                        </td></tr>`
                )
                .join("");
            return `<article class="floor">
                <div class="floor-head">
                    <h3>Floor ${f.floor_number}</h3>
                    <span class="count ${f.available === 0 ? "full" : ""}">${f.occupied} / ${f.capacity}${f.available === 0 ? " · FULL" : ""}</span>
                    <div class="row-actions">
                        <button data-action="park" data-floor="${f.floor_number}" ${f.available === 0 ? "disabled" : ""}>Park here</button>
                        <button data-action="edit-floor" data-floor="${f.floor_number}">Edit capacity</button>
                        <button data-action="delete-floor" data-floor="${f.floor_number}">Delete</button>
                    </div>
                </div>
                <div class="bar"><div class="${f.available === 0 ? "full" : ""}" style="width:${pct}%"></div></div>
                ${
                    f.vehicles.length
                        ? `<div class="scroll"><table><thead><tr><th>Plate</th><th>Type</th><th>Colour</th><th>Brand</th><th>Model</th><th>Entered</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
                        : `<p class="empty">No vehicles on this floor.</p>`
                }
            </article>`;
        })
        .join("");
}

// ---- Floor dialog (add floor / edit capacity) ------------------------------
let editingFloor = null;

function openFloorDialog(floor = null) {
    editingFloor = floor;
    $("#floor-title").textContent = floor ? `Edit capacity · Floor ${floor.floor_number}` : "Add floor";
    $("#f-number").value = floor ? floor.floor_number : floors.length ? Math.max(...floors.map((f) => f.floor_number)) + 1 : 1;
    $("#f-number").disabled = !!floor;
    $("#f-capacity").value = floor ? floor.capacity : "";
    $("#floor-error").hidden = true;
    $("#floor-dialog").showModal();
}

$("#floor-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const capacity = Number($("#f-capacity").value);
    try {
        if (editingFloor) {
            await api("PATCH", `/floors/${editingFloor.floor_number}`, { capacity });
        } else {
            await api("POST", "/floors", [{ floor_number: Number($("#f-number").value), capacity }]);
        }
        $("#floor-dialog").close();
        await load();
    } catch (err) {
        $("#floor-error").textContent = err.message;
        $("#floor-error").hidden = false;
    }
});

// ---- Vehicle dialog (park / edit) ------------------------------------------
let editingPlate = null;

function openVehicleDialog(vehicle = null, floorNumber = null) {
    if (!floors.length) return showMsg("Add a floor first.", true);
    editingPlate = vehicle ? vehicle.number_plate : null;
    $("#vehicle-title").textContent = vehicle ? `Edit ${vehicle.number_plate}` : "Park a vehicle";

    $("#v-floor").innerHTML = floors
        .map((f) => `<option value="${f.floor_number}" ${f.available === 0 ? "disabled" : ""}>Floor ${f.floor_number} (${f.available} free)</option>`)
        .join("");
    // In edit mode, keep the vehicle's own floor selectable even if that floor is full
    if (vehicle) $("#v-floor").querySelector(`[value="${vehicle.floor_number}"]`).disabled = false;

    $("#v-floor").value = vehicle ? vehicle.floor_number : floorNumber ?? floors.find((f) => f.available > 0)?.floor_number ?? floors[0].floor_number;
    $("#v-plate").value = vehicle?.number_plate ?? "";
    $("#v-type").value = vehicle?.vehicle_type ?? "";
    $("#v-colour").value = vehicle?.colour ?? "";
    $("#v-brand").value = vehicle?.brand ?? "";
    $("#v-model").value = vehicle?.model ?? "";
    $("#vehicle-error").hidden = true;
    $("#vehicle-dialog").showModal();
}

$("#vehicle-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fields = {
        number_plate: $("#v-plate").value,
        vehicle_type: $("#v-type").value,
        colour: $("#v-colour").value,
        brand: $("#v-brand").value,
        model: $("#v-model").value,
    };
    const floor = Number($("#v-floor").value);
    try {
        if (editingPlate) {
            await api("PATCH", `/vehicles/${encodeURIComponent(editingPlate)}`, { ...fields, floor_number: floor });
        } else {
            await api("POST", `/floors/${floor}/vehicles`, fields);
        }
        $("#vehicle-dialog").close();
        await load();
    } catch (err) {
        $("#vehicle-error").textContent = err.message;
        $("#vehicle-error").hidden = false;
    }
});

// ---- Buttons ---------------------------------------------------------------
$("#btn-add-floor").addEventListener("click", () => openFloorDialog());
$("#btn-park").addEventListener("click", () => openVehicleDialog());
$("#btn-refresh").addEventListener("click", load);
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

$("#floors").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const floor = floors.find((f) => f.floor_number === Number(btn.dataset.floor));
    const vehicle = floors.flatMap((f) => f.vehicles).find((v) => v.number_plate === btn.dataset.plate);

    try {
        switch (btn.dataset.action) {
            case "park":
                return openVehicleDialog(null, floor.floor_number);
            case "edit-floor":
                return openFloorDialog(floor);
            case "edit-vehicle":
                return openVehicleDialog(vehicle);
            case "delete-floor": {
                const msg = floor.occupied
                    ? `Floor ${floor.floor_number} has ${floor.occupied} vehicle(s). Delete it and their records?`
                    : `Delete floor ${floor.floor_number}?`;
                if (!confirm(msg)) return;
                await api("DELETE", `/floors/${floor.floor_number}${floor.occupied ? "?force=true" : ""}`);
                showMsg(`Floor ${floor.floor_number} deleted.`);
                return load();
            }
            case "remove-vehicle":
                if (!confirm(`Remove ${vehicle.number_plate}?`)) return;
                await api("DELETE", `/vehicles/${encodeURIComponent(vehicle.number_plate)}`);
                showMsg(`${vehicle.number_plate} removed.`);
                return load();
        }
    } catch (err) {
        showMsg(err.message, true);
    }
});

load();