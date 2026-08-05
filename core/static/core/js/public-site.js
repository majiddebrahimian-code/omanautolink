(() => {
    const menuToggle = document.querySelector("[data-menu-toggle]");
    const navigation = document.querySelector("[data-primary-navigation]");

    if (menuToggle && navigation) {
        menuToggle.addEventListener("click", () => {
            const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
            menuToggle.setAttribute("aria-expanded", String(!isOpen));
            navigation.classList.toggle("is-open", !isOpen);
        });

        navigation.querySelectorAll("a").forEach((link) => {
            link.addEventListener("click", () => {
                menuToggle.setAttribute("aria-expanded", "false");
                navigation.classList.remove("is-open");
            });
        });
    }

    const setupSpinViewer = (viewer) => {
        const framesElement = document.getElementById(
            viewer.dataset.spinFramesId,
        );
        const image = viewer.querySelector("[data-spin-image]");

        if (!framesElement || !image) {
            return;
        }

        let frameUrls;
        try {
            frameUrls = JSON.parse(framesElement.textContent);
        } catch (_error) {
            return;
        }

        if (!Array.isArray(frameUrls) || frameUrls.length < 2) {
            return;
        }

        let currentFrame = 0;
        let pointerId = null;
        let lastPointerX = 0;
        let carry = 0;
        let preloaded = false;
        const pixelsPerFrame = 14;

        const showFrame = (frameIndex) => {
            currentFrame =
                ((frameIndex % frameUrls.length) + frameUrls.length) %
                frameUrls.length;
            image.src = frameUrls[currentFrame];
            viewer.dataset.spinFrame = String(currentFrame + 1);
        };

        const preloadRemainingFrames = () => {
            if (preloaded) {
                return;
            }
            preloaded = true;

            frameUrls.forEach((url, index) => {
                if (index === currentFrame) {
                    return;
                }
                const preloadImage = new Image();
                preloadImage.src = url;
            });
        };

        viewer.addEventListener("pointerdown", (event) => {
            if (event.pointerType === "mouse" && event.button !== 0) {
                return;
            }

            pointerId = event.pointerId;
            lastPointerX = event.clientX;
            carry = 0;
            viewer.setPointerCapture(pointerId);
            viewer.classList.add("is-dragging");
            preloadRemainingFrames();
        });

        viewer.addEventListener("pointermove", (event) => {
            if (event.pointerId !== pointerId) {
                return;
            }

            carry += event.clientX - lastPointerX;
            lastPointerX = event.clientX;
            const movement = Math.trunc(carry / pixelsPerFrame);
            if (!movement) {
                return;
            }

            showFrame(currentFrame - movement);
            carry -= movement * pixelsPerFrame;
        });

        const stopDragging = (event) => {
            if (event.pointerId !== pointerId) {
                return;
            }

            if (viewer.hasPointerCapture(pointerId)) {
                viewer.releasePointerCapture(pointerId);
            }
            pointerId = null;
            carry = 0;
            viewer.classList.remove("is-dragging");
        };

        viewer.addEventListener("pointerup", stopDragging);
        viewer.addEventListener("pointercancel", stopDragging);
        viewer.addEventListener("lostpointercapture", () => {
            pointerId = null;
            carry = 0;
            viewer.classList.remove("is-dragging");
        });
        viewer.addEventListener("dragstart", (event) => event.preventDefault());

        viewer.addEventListener("keydown", (event) => {
            if (event.key === "ArrowRight") {
                event.preventDefault();
                preloadRemainingFrames();
                showFrame(currentFrame - 1);
            }
            if (event.key === "ArrowLeft") {
                event.preventDefault();
                preloadRemainingFrames();
                showFrame(currentFrame + 1);
            }
        });

        viewer.dataset.spinReady = "true";
    };

    document.querySelectorAll("[data-spin-viewer]").forEach(setupSpinViewer);

    const setupVehicleGallery = (gallery) => {
        const mainArea = gallery.querySelector("[data-gallery-main]");
        const mainImage = gallery.querySelector("[data-gallery-main-image]");
        const spinViewer = gallery.querySelector("[data-gallery-spin-viewer]");
        const photoControls = Array.from(
            gallery.querySelectorAll("[data-gallery-thumbnail]"),
        );
        const spinControl = gallery.querySelector("[data-gallery-spin-control]");
        const controls = [...photoControls];

        if (spinControl) {
            controls.unshift(spinControl);
        }

        if (!controls.length || (!mainImage && !spinViewer)) {
            return;
        }

        let changeSequence = 0;

        const setActiveControl = (activeControl) => {
            controls.forEach((control) => {
                const isActive = control === activeControl;
                control.classList.toggle("is-active", isActive);
                control.setAttribute("aria-pressed", String(isActive));
            });
        };

        const switchMainMedia = (applyChange) => {
            if (!mainArea) {
                applyChange();
                return;
            }

            mainArea.classList.add("is-switching-media");
            window.setTimeout(() => {
                applyChange();
                window.requestAnimationFrame(() => {
                    mainArea.classList.remove("is-switching-media");
                });
            }, 130);
        };

        const showPhoto = (control) => {
            const imageUrl = control.dataset.galleryImageSrc;
            if (!mainImage || !imageUrl) {
                return;
            }

            const requestedChange = ++changeSequence;
            const preloadImage = new Image();
            let hasAppliedPhoto = false;
            const applyPhoto = () => {
                if (hasAppliedPhoto || requestedChange !== changeSequence) {
                    return;
                }

                hasAppliedPhoto = true;

                switchMainMedia(() => {
                    if (requestedChange !== changeSequence) {
                        return;
                    }

                    mainImage.src = imageUrl;
                    mainImage.alt = control.dataset.galleryImageAlt || "";
                    mainImage.hidden = false;

                    if (spinViewer) {
                        spinViewer.hidden = true;
                    }

                    gallery.dataset.galleryMode = "photo";
                });
            };

            preloadImage.addEventListener("load", applyPhoto, { once: true });
            preloadImage.src = imageUrl;
            if (preloadImage.complete && preloadImage.naturalWidth > 0) {
                applyPhoto();
            }
            setActiveControl(control);
        };

        const showSpin = () => {
            if (!spinViewer || !spinControl) {
                return;
            }

            ++changeSequence;
            switchMainMedia(() => {
                spinViewer.hidden = false;
                if (mainImage) {
                    mainImage.hidden = true;
                }

                gallery.dataset.galleryMode = "spin";
            });
            setActiveControl(spinControl);
        };

        photoControls.forEach((control) => {
            control.addEventListener("click", () => showPhoto(control));
        });

        if (spinControl) {
            spinControl.addEventListener("click", showSpin);
        }

        gallery.dataset.galleryReady = "true";
    };

    document.querySelectorAll("[data-vehicle-gallery]").forEach(setupVehicleGallery);
})();
