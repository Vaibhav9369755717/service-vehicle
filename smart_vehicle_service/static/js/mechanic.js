document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.querySelector(".mechanic-sidebar");
    document.querySelectorAll("[data-mechanic-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            sidebar.classList.add("is-open");
            button.setAttribute("aria-expanded", "true");
        });
    });
    document.querySelectorAll("[data-mechanic-close]").forEach((button) => {
        button.addEventListener("click", () => {
            sidebar.classList.remove("is-open");
            document.querySelector("[data-mechanic-toggle]")?.setAttribute("aria-expanded", "false");
        });
    });
});