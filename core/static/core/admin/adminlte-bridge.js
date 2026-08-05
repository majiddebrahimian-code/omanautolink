(function () {
  "use strict";

  var body = document.body;
  var sidebar = document.getElementById("nav-sidebar");
  var toggle = document.querySelector("[data-admin-sidebar-toggle]");
  var mobileBreakpoint = window.matchMedia("(max-width: 991.98px)");

  function isMobile() {
    return mobileBreakpoint.matches;
  }

  function syncToggleState() {
    if (!toggle) return;
    var open = isMobile()
      ? body.classList.contains("sidebar-open")
      : !body.classList.contains("sidebar-collapse");
    toggle.setAttribute("aria-expanded", String(open));
  }

  function closeMobileSidebar() {
    body.classList.remove("sidebar-open");
    syncToggleState();
  }

  if (sidebar && toggle) {
    toggle.addEventListener("click", function () {
      if (isMobile()) {
        body.classList.toggle("sidebar-open");
      } else {
        body.classList.toggle("sidebar-collapse");
      }
      syncToggleState();
    });

    document.addEventListener("click", function (event) {
      if (!isMobile() || !body.classList.contains("sidebar-open")) return;
      if (!sidebar.contains(event.target) && !toggle.contains(event.target)) {
        closeMobileSidebar();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isMobile()) closeMobileSidebar();
    });

    mobileBreakpoint.addEventListener("change", function () {
      body.classList.remove("sidebar-open");
      syncToggleState();
    });

    syncToggleState();
  }

  document.querySelectorAll("[data-admin-tree-toggle]").forEach(function (treeToggle) {
    treeToggle.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var group = treeToggle.closest("[data-admin-nav-group]");
      if (group) group.classList.toggle("menu-open");
    });
  });

  var activePath = window.location.pathname.replace(/\/+$/, "") || "/";
  document.querySelectorAll("#nav-sidebar a[href]").forEach(function (link) {
    var linkPath;
    try {
      linkPath = new URL(link.href, window.location.origin).pathname.replace(/\/+$/, "") || "/";
    } catch (error) {
      return;
    }

    if (linkPath === activePath) {
      link.classList.add("active");
      var ownerGroup = link.closest("[data-admin-nav-group]");
      if (ownerGroup) {
        ownerGroup.classList.add("menu-open");
        var ownerLink = ownerGroup.querySelector("[data-admin-nav-group-link]");
        if (ownerLink) ownerLink.classList.add("active");
      }
    }
  });

  var menuFilter = document.querySelector("[data-admin-nav-filter]");
  if (menuFilter) {
    menuFilter.addEventListener("input", function () {
      var phrase = menuFilter.value.trim().toLocaleLowerCase("fa-IR");
      document.querySelectorAll("[data-admin-nav-group]").forEach(function (group) {
        var matches = !phrase || group.textContent.toLocaleLowerCase("fa-IR").indexOf(phrase) !== -1;
        group.hidden = !matches;
        if (matches && phrase) group.classList.add("menu-open");
      });
    });
  }
}());
