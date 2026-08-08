(() => {
    const body = document.body;
    const toggleButton = document.querySelector("[data-panel-sidebar-toggle]");
    const backdrop = document.querySelector("[data-panel-sidebar-backdrop]");

    function closeSidebar() {
        if (!toggleButton) {
            return;
        }

        body.classList.remove("panel-sidebar-open");
        toggleButton.setAttribute("aria-expanded", "false");
    }

    if (toggleButton && backdrop) {
        toggleButton.addEventListener("click", () => {
            const isOpen = body.classList.toggle("panel-sidebar-open");
            toggleButton.setAttribute("aria-expanded", String(isOpen));
        });

        backdrop.addEventListener("click", closeSidebar);

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeSidebar();
            }
        });
    }

    const userMenu = document.querySelector("[data-user-menu]");
    const userMenuTrigger = document.querySelector("[data-user-menu-trigger]");
    const userMenuDropdown = document.querySelector("[data-user-menu-dropdown]");

    function closeUserMenu() {
        if (!userMenu || !userMenuTrigger || !userMenuDropdown) {
            return;
        }
        userMenu.classList.remove("is-open");
        userMenuTrigger.setAttribute("aria-expanded", "false");
        userMenuDropdown.hidden = true;
    }

    if (userMenu && userMenuTrigger && userMenuDropdown) {
        userMenuTrigger.addEventListener("click", () => {
            const willOpen = !userMenu.classList.contains("is-open");
            closeUserMenu();
            if (willOpen) {
                userMenu.classList.add("is-open");
                userMenuTrigger.setAttribute("aria-expanded", "true");
                userMenuDropdown.hidden = false;
            }
        });

        document.addEventListener("click", (event) => {
            if (!userMenu.contains(event.target)) {
                closeUserMenu();
            }
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeUserMenu();
            }
        });
    }

    document.querySelectorAll("[data-copy-text]").forEach((button) => {
        button.addEventListener("click", async () => {
            const text = button.dataset.copyText || "";

            if (!text) {
                return;
            }

            try {
                await navigator.clipboard.writeText(text);
                button.setAttribute("title", "کپی شد");
                button.setAttribute("aria-label", "کد رهگیری کپی شد");
                button.classList.add("is-copied");

                window.setTimeout(() => {
                    button.setAttribute("title", "کپی کد رهگیری");
                    button.setAttribute("aria-label", "کپی کد رهگیری");
                    button.classList.remove("is-copied");
                }, 1800);
            } catch (error) {
                button.setAttribute("title", "کپی خودکار ممکن نیست");
            }
        });
    });
})();
