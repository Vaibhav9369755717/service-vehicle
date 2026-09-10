document.addEventListener("DOMContentLoaded", () => {
    const menuToggle = document.querySelector(".menu-toggle");
    const navLinks = document.querySelector(".nav-links");

    if (menuToggle && navLinks) {
        menuToggle.addEventListener("click", () => {
            const isOpen = navLinks.classList.toggle("is-open");
            menuToggle.setAttribute("aria-expanded", String(isOpen));
        });
    }

    document.querySelectorAll(".flash-close").forEach((button) => {
        button.addEventListener("click", () => button.parentElement.remove());
    });

    const year = document.querySelector(".current-year");
    if (year) year.textContent = new Date().getFullYear();
});