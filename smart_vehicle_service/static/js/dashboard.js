document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.querySelector(".dashboard-sidebar");
    const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
    const sidebarClosers = document.querySelectorAll("[data-sidebar-close]");

    const closeSidebar = () => {
        sidebar?.classList.remove("is-open");
        sidebarToggle?.setAttribute("aria-expanded", "false");
    };

    sidebarToggle?.addEventListener("click", () => {
        const isOpen = sidebar.classList.toggle("is-open");
        sidebarToggle.setAttribute("aria-expanded", String(isOpen));
    });
    sidebarClosers.forEach((closer) => closer.addEventListener("click", closeSidebar));

    const dropdownTriggers = document.querySelectorAll("[data-dropdown-trigger]");
    dropdownTriggers.forEach((trigger) => {
        trigger.addEventListener("click", (event) => {
            event.stopPropagation();
            const target = document.getElementById(trigger.dataset.dropdownTrigger);
            const wasHidden = target.hidden;
            document.querySelectorAll(".dropdown").forEach((dropdown) => { dropdown.hidden = true; });
            dropdownTriggers.forEach((item) => item.setAttribute("aria-expanded", "false"));
            target.hidden = !wasHidden;
            trigger.setAttribute("aria-expanded", String(wasHidden));
        });
    });

    document.addEventListener("click", () => {
        document.querySelectorAll(".dropdown").forEach((dropdown) => { dropdown.hidden = true; });
        dropdownTriggers.forEach((trigger) => trigger.setAttribute("aria-expanded", "false"));
    });

    document.querySelectorAll("[data-confirm-delete]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const vehicleName = form.dataset.confirmDelete;
            if (!window.confirm(`Delete ${vehicleName}? This action cannot be undone.`)) {
                event.preventDefault();
            }
        });
    });

    const bookingDate = document.querySelector("[data-booking-date]");
    if (bookingDate && !bookingDate.min) {
        bookingDate.min = new Date().toISOString().split("T")[0];
    }

    const vehicleSelect = document.querySelector("[data-vehicle-select]");
    const vehiclePreview = document.querySelector("[data-vehicle-preview]");
    const updateVehiclePreview = () => {
        const selected = vehicleSelect?.selectedOptions[0];
        if (vehiclePreview && selected?.dataset.vehicleLabel) {
            vehiclePreview.textContent = `Selected: ${selected.dataset.vehicleLabel}`;
        } else if (vehiclePreview) {
            vehiclePreview.textContent = "Select the vehicle that needs attention.";
        }
    };
    vehicleSelect?.addEventListener("change", updateVehiclePreview);
    updateVehiclePreview();

    document.querySelectorAll("[data-confirm-booking]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm("Submit this service booking request?")) {
                event.preventDefault();
            }
        });
    });
});