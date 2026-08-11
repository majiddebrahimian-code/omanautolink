(() => {
    const body = document.body;
    const toggleButton = document.querySelector("[data-panel-sidebar-toggle]");
    const backdrop = document.querySelector("[data-panel-sidebar-backdrop]");

    const desktopSidebarQuery = window.matchMedia("(min-width: 961px)");
    const sidebarPreferenceKey = "oml-backoffice-sidebar-collapsed";

    function syncSidebarToggle() {
        if (!toggleButton) {
            return;
        }
        if (desktopSidebarQuery.matches) {
            toggleButton.setAttribute(
                "aria-expanded",
                String(!body.classList.contains("panel-sidebar-collapsed")),
            );
        } else {
            toggleButton.setAttribute(
                "aria-expanded",
                String(body.classList.contains("panel-sidebar-open")),
            );
        }
    }

    function closeSidebar() {
        if (!toggleButton || desktopSidebarQuery.matches) {
            return;
        }
        body.classList.remove("panel-sidebar-open");
        syncSidebarToggle();
    }

    if (desktopSidebarQuery.matches && localStorage.getItem(sidebarPreferenceKey) === "true") {
        body.classList.add("panel-sidebar-collapsed");
    }
    syncSidebarToggle();

    if (toggleButton && backdrop) {
        toggleButton.addEventListener("click", () => {
            if (desktopSidebarQuery.matches) {
                const isCollapsed = body.classList.toggle("panel-sidebar-collapsed");
                localStorage.setItem(sidebarPreferenceKey, String(isCollapsed));
            } else {
                body.classList.toggle("panel-sidebar-open");
            }
            syncSidebarToggle();
        });

        backdrop.addEventListener("click", closeSidebar);

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeSidebar();
            }
        });

        desktopSidebarQuery.addEventListener("change", () => {
            body.classList.remove("panel-sidebar-open");
            syncSidebarToggle();
        });
    }

    const navigationGroups = document.querySelectorAll(
        ".backoffice-navigation .backoffice-nav-group"
    );

    navigationGroups.forEach((group) => {
        const summary = group.querySelector(":scope > summary");

        if (!summary) {
            return;
        }

        summary.addEventListener("click", () => {
            // Native <details> changes its state after the click event. Queue
            // the accordion update so the newly opened section remains open.
            window.setTimeout(() => {
                if (!group.open) {
                    return;
                }

                navigationGroups.forEach((otherGroup) => {
                    if (otherGroup !== group) {
                        otherGroup.open = false;
                    }
                });
            }, 0);
        });
    });

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

    const selectedPageSize = new URLSearchParams(window.location.search).get("per_page");
    if (selectedPageSize) {
        document.querySelectorAll(".backoffice-pagination a").forEach((link) => {
            const url = new URL(link.href, window.location.origin);
            url.searchParams.set("per_page", selectedPageSize);
            link.href = url.pathname + "?" + url.searchParams.toString();
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
