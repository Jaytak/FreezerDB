(() => {
    const params = new URLSearchParams(window.location.search);
    const focusTarget = params.get("focus");
    let latestVersion = null;
    let refreshInFlight = false;
    let liveLogTimer = null;

    const bindNavigation = () => {
        const topbar = document.querySelector(".topbar");
        const brand = document.querySelector(".brand-block");
        const toggle = document.querySelector("[data-menu-toggle]");
        const nav = document.querySelector("[data-main-nav]");
        if (!topbar || !brand || !toggle || !nav) {
            return;
        }
        const updateNavigationMode = () => {
            const title = brand.querySelector("h1");
            const eyebrow = brand.querySelector(".eyebrow");
            const textWidth = (element) => {
                if (!element) {
                    return 0;
                }
                const measure = element.cloneNode(true);
                Object.assign(measure.style, {
                    display: "block",
                    position: "fixed",
                    visibility: "hidden",
                    width: "max-content",
                });
                document.body.appendChild(measure);
                const width = measure.getBoundingClientRect().width;
                measure.remove();
                return width;
            };
            const navMeasure = nav.cloneNode(true);
            navMeasure.classList.remove("open");
            Object.assign(navMeasure.style, {
                display: "flex",
                flexWrap: "nowrap",
                maxHeight: "none",
                opacity: "0",
                padding: "0",
                pointerEvents: "none",
                position: "fixed",
                visibility: "hidden",
                width: "max-content",
            });
            document.body.appendChild(navMeasure);
            const navWidth = navMeasure.getBoundingClientRect().width;
            navMeasure.remove();
            const topbarStyle = getComputedStyle(topbar);
            const usableWidth =
                topbar.clientWidth -
                parseFloat(topbarStyle.paddingLeft) -
                parseFloat(topbarStyle.paddingRight);
            const brandWidth = Math.max(textWidth(title), textWidth(eyebrow));
            const requiredWidth = brandWidth + navWidth + parseFloat(topbarStyle.gap || "24");
            const compact = window.innerWidth <= 699 || requiredWidth > usableWidth;
            topbar.classList.toggle("compact-nav", compact);
            topbar.classList.add("nav-ready");
            if (!compact) {
                nav.classList.remove("open");
                topbar.classList.remove("nav-open");
                toggle.classList.remove("open");
                toggle.setAttribute("aria-expanded", "false");
                toggle.setAttribute("aria-label", "Open navigation");
            }
        };
        updateNavigationMode();
        if (toggle.dataset.boundMenu === "true") {
            return;
        }
        toggle.dataset.boundMenu = "true";
        let resizeFrame = 0;
        window.addEventListener("resize", () => {
            window.cancelAnimationFrame(resizeFrame);
            resizeFrame = window.requestAnimationFrame(updateNavigationMode);
        });
        toggle.addEventListener("click", () => {
            const open = nav.classList.toggle("open");
            topbar.classList.toggle("nav-open", open);
            toggle.classList.toggle("open", open);
            toggle.setAttribute("aria-expanded", String(open));
            toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
        });
        nav.addEventListener("click", (event) => {
            if (event.target.closest("a")) {
                nav.classList.remove("open");
                topbar.classList.remove("nav-open");
                toggle.classList.remove("open");
                toggle.setAttribute("aria-expanded", "false");
            }
        });
    };

    const bindExclusiveDropdowns = () => {
        document.querySelectorAll(".filter-dropdown").forEach((dropdown) => {
            if (dropdown.dataset.boundExclusive === "true") {
                return;
            }
            dropdown.dataset.boundExclusive = "true";
            dropdown.addEventListener("toggle", () => {
                if (!dropdown.open) {
                    return;
                }
                document.querySelectorAll(".filter-dropdown[open]").forEach((other) => {
                    if (other !== dropdown) {
                        other.open = false;
                    }
                });
            });
        });
        if (document.body.dataset.boundDropdownOutside !== "true") {
            document.body.dataset.boundDropdownOutside = "true";
            document.addEventListener("click", (event) => {
                if (event.target.closest(".filter-dropdown")) {
                    return;
                }
                document.querySelectorAll(".filter-dropdown[open]").forEach((dropdown) => {
                    dropdown.open = false;
                });
            });
        }
    };

    const bindTableScale = () => {
        document.querySelectorAll("[data-table-scale]").forEach((slider) => {
            if (slider.dataset.boundTableScale === "true") {
                return;
            }
            slider.dataset.boundTableScale = "true";
            const panel = slider.closest("[data-scalable-table]");
            const key = `freezerStock:tableScale:${panel?.dataset.tableKey || window.location.pathname}`;
            const saved = window.localStorage.getItem(key);
            if (saved) {
                slider.value = saved;
            }
            const apply = (resetWhenHidden = false) => {
                const control = slider.closest(".table-scale-control");
                const hidden = control && getComputedStyle(control).display === "none";
                if (hidden && resetWhenHidden) {
                    slider.value = "100";
                    window.localStorage.removeItem(key);
                }
                const scale = Number(slider.value) / 100;
                const baseWidth = Number(panel?.dataset.tableBaseWidth || "920");
                panel?.style.setProperty("--table-font-size", `${Math.max(0.68, 0.95 * scale)}rem`);
                panel?.style.setProperty("--table-cell-pad-y", `${Math.max(6, 14 * scale)}px`);
                panel?.style.setProperty("--table-cell-pad-x", `${Math.max(5, 16 * scale)}px`);
                panel?.style.setProperty("--table-action-pad", `${Math.max(5, 10 * scale)}px`);
                panel?.style.setProperty("--table-control-size", `${Math.max(26, 34 * scale)}px`);
                panel?.style.setProperty("--table-badge-font", `${Math.max(0.62, 0.78 * scale)}rem`);
                panel?.style.setProperty("--table-min-width", `${Math.round(baseWidth * scale)}px`);
                if (!hidden) {
                    window.localStorage.setItem(key, slider.value);
                }
            };
            slider.applyTableScale = apply;
            apply(true);
            slider.addEventListener("input", apply);
        });
        if (document.body.dataset.boundTableScaleResize !== "true") {
            document.body.dataset.boundTableScaleResize = "true";
            let resizeFrame = 0;
            window.addEventListener("resize", () => {
                window.cancelAnimationFrame(resizeFrame);
                resizeFrame = window.requestAnimationFrame(() => {
                    document.querySelectorAll("[data-table-scale]").forEach((slider) => {
                        slider.applyTableScale?.(true);
                    });
                });
            });
        }
    };

    const bindLiveFilters = () => {
        document.querySelectorAll("form[data-live-filter]").forEach((form) => {
            if (form.dataset.boundLiveFilter === "true") {
                return;
            }
            form.dataset.boundLiveFilter = "true";
            let timer = null;
            const apply = async () => {
                const params = new URLSearchParams(new FormData(form));
                for (const [key, value] of [...params.entries()]) {
                    if (!String(value).trim()) {
                        params.delete(key);
                    }
                }
                const query = params.toString();
                window.history.replaceState({}, "", `${form.action}${query ? `?${query}` : ""}`);
                await refreshMain(true);
            };
            form.addEventListener("submit", (event) => {
                event.preventDefault();
                apply();
            });
            form.addEventListener("input", (event) => {
                if (!event.target.matches("input")) {
                    return;
                }
                window.clearTimeout(timer);
                timer = window.setTimeout(apply, 250);
            });
            form.addEventListener("change", (event) => {
                if (event.target.matches("select, input[type='date'], input[type='number'], input[type='checkbox'], input[type='radio']")) {
                    window.clearTimeout(timer);
                    apply();
                }
            });
        });
    };

    const bindRememberCategory = () => {
        document.querySelectorAll("[data-remember-category]").forEach((categorySelect) => {
            if (categorySelect.dataset.boundRememberCategory === "true") {
                return;
            }
            categorySelect.dataset.boundRememberCategory = "true";
            const remembered = window.localStorage.getItem("freezerStock:lastCategory");
            const isBlankFood = !categorySelect.form?.querySelector("input[name='name']")?.value;
            if (remembered && isBlankFood) {
                const hasOption = Array.from(categorySelect.options).some((option) => option.value === remembered);
                if (hasOption) {
                    categorySelect.value = remembered;
                }
            }
            categorySelect.addEventListener("change", () => {
                if (categorySelect.value) {
                    window.localStorage.setItem("freezerStock:lastCategory", categorySelect.value);
                }
            });
            categorySelect.form?.addEventListener("submit", () => {
                const custom = categorySelect.form.querySelector("input[name='category_custom']");
                const value = custom?.value.trim() || categorySelect.value;
                if (value) {
                    window.localStorage.setItem("freezerStock:lastCategory", value);
                }
            });
        });
        document.querySelectorAll("select[name='freezer_id']").forEach((freezerSelect) => {
            if (freezerSelect.dataset.boundRememberFreezer === "true") {
                return;
            }
            freezerSelect.dataset.boundRememberFreezer = "true";
            const remembered = window.localStorage.getItem("freezerStock:lastFreezer");
            const isBlankFood = !freezerSelect.form?.querySelector("input[name='name']")?.value;
            if (remembered && isBlankFood && [...freezerSelect.options].some((option) => option.value === remembered)) {
                freezerSelect.value = remembered;
            }
            const remember = () => {
                if (freezerSelect.value && freezerSelect.value !== "__add__") {
                    window.localStorage.setItem("freezerStock:lastFreezer", freezerSelect.value);
                }
            };
            freezerSelect.addEventListener("change", remember);
            freezerSelect.form?.addEventListener("submit", remember);
        });
    };

    let focusElement = null;
    if (focusTarget) {
        focusElement = document.querySelector(`[data-focus="${CSS.escape(focusTarget)}"]`);
    }
    focusElement = focusElement || document.querySelector("[data-autofocus]");
    if (focusElement) {
        focusElement.focus();
        if (typeof focusElement.select === "function") {
            focusElement.select();
        }
    }

    const bindAutoSubmit = () => {
        document.querySelectorAll("[data-auto-submit]").forEach((form) => {
            if (form.dataset.boundAutoSubmit === "true") {
                return;
            }
            form.dataset.boundAutoSubmit = "true";
            form.addEventListener("change", (event) => {
                if (event.target.matches("input, select")) {
                    form.requestSubmit();
                }
            });
        });
    };

    const bindUnitControls = () => {
        document.querySelectorAll("[data-add-select]").forEach((select) => {
            if (select.dataset.boundAddSelect === "true") {
                return;
            }
            select.dataset.boundAddSelect = "true";
            const custom = select.closest(".select-add-control")?.querySelector("[data-add-input]");
            const sync = () => {
                if (!custom) {
                    return;
                }
                custom.hidden = select.value !== "";
                if (select.value !== "") {
                    custom.value = "";
                }
            };
            sync();
            select.addEventListener("change", sync);
        });
        document.querySelectorAll("[data-unit-custom]").forEach((input) => {
            if (input.dataset.boundLowercase === "true") {
                return;
            }
            input.dataset.boundLowercase = "true";
            input.addEventListener("input", () => {
                input.value = input.value.toLowerCase();
            });
        });
    };

    const bindStapleControls = () => {
        document.querySelectorAll("[data-staple-toggle]").forEach((toggle) => {
            if (toggle.dataset.boundStaple === "true") {
                return;
            }
            toggle.dataset.boundStaple = "true";
            const control = toggle.closest("[data-staple-control]");
            const sync = (animate = false) => {
                if (!control) {
                    return;
                }
                window.clearTimeout(control.stapleCloseTimer);
                if (toggle.checked) {
                    control.classList.remove("is-closing");
                    control.classList.add("is-open");
                    return;
                }
                if (animate && control.classList.contains("is-open")) {
                    control.classList.add("is-closing");
                    control.classList.remove("is-open");
                    control.stapleCloseTimer = window.setTimeout(() => {
                        control.classList.remove("is-closing");
                    }, 320);
                    return;
                }
                control.classList.remove("is-open", "is-closing");
            };
            sync(false);
            toggle.addEventListener("change", () => sync(true));
        });
    };

    const bindQuickAdd = () => {
        const modal = document.querySelector("[data-quick-add-modal]");
        const form = modal?.querySelector("[data-quick-add-form]");
        const title = modal?.querySelector("[data-quick-add-title]");
        const kindInput = modal?.querySelector("[data-quick-add-kind]");
        const nameInput = modal?.querySelector("[data-quick-add-name]");
        const nameLabel = modal?.querySelector("[data-quick-add-name-label]");
        const error = modal?.querySelector("[data-quick-add-error]");
        const cancel = modal?.querySelector("[data-quick-add-cancel]");
        if (!modal || !form || !title || !kindInput || !nameInput || !nameLabel || !error || !cancel) {
            return;
        }

        let target = null;
        const labels = {
            freezer: ["Add Freezer", "Freezer name"],
            person: ["Add Person", "Person name"],
            unit: ["Add Unit", "Unit name"],
            category: ["Add Category", "Category name"],
        };
        const close = () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
            form.reset();
            error.hidden = true;
            target = null;
        };
        const open = (kind, source) => {
            const copy = labels[kind];
            if (!copy) {
                return;
            }
            target = source;
            kindInput.value = kind;
            title.textContent = copy[0];
            nameLabel.textContent = copy[1];
            nameInput.placeholder = copy[1];
            error.hidden = true;
            modal.hidden = false;
            document.body.classList.add("modal-open");
            nameInput.focus();
        };
        const addPersonOption = (item) => {
            const container = document.querySelector("[data-people-options]");
            if (!container) {
                return;
            }
            container.querySelector(".compact")?.remove();
            const label = document.createElement("label");
            label.className = "check-option";
            label.innerHTML = `<input type="checkbox" name="person_ids" value="${item.id}" checked><span></span>`;
            label.querySelector("span").textContent = item.name;
            container.append(label);
        };

        document.querySelectorAll("[data-quick-add-select]").forEach((select) => {
            if (select.dataset.boundQuickAdd === "true") {
                return;
            }
            select.dataset.boundQuickAdd = "true";
            select.dataset.previousValue = select.value;
            select.addEventListener("focus", () => {
                if (select.value !== "__add__") {
                    select.dataset.previousValue = select.value;
                }
            });
            select.addEventListener("change", () => {
                if (select.value === "__add__") {
                    const previous = select.dataset.previousValue || "";
                    select.value = previous;
                    open(select.dataset.quickAddSelect, select);
                } else {
                    select.dataset.previousValue = select.value;
                }
            });
        });
        document.querySelectorAll("[data-quick-add-button]").forEach((button) => {
            if (button.dataset.boundQuickAdd === "true") {
                return;
            }
            button.dataset.boundQuickAdd = "true";
            button.addEventListener("click", () => open(button.dataset.quickAddButton, button));
        });
        if (form.dataset.boundQuickAddForm !== "true") {
            form.dataset.boundQuickAddForm = "true";
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                const kind = kindInput.value;
                const data = new URLSearchParams(new FormData(form));
                const response = await fetch(`/api/quick-add/${encodeURIComponent(kind)}`, {
                    method: "POST",
                    body: data,
                    headers: { "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded" },
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.item) {
                    error.textContent = result.errors?.join(" ") || "Could not add this entry.";
                    error.hidden = false;
                    return;
                }
                if (kind === "person") {
                    addPersonOption(result.item);
                } else if (target?.matches("select")) {
                    const value = kind === "freezer" ? String(result.item.id) : result.item.name;
                    const option = document.createElement("option");
                    option.value = value;
                    option.textContent = result.item.name;
                    const addOption = target.querySelector('option[value="__add__"]');
                    target.insertBefore(option, addOption);
                    target.value = value;
                    target.dataset.previousValue = value;
                    target.dispatchEvent(new Event("change", { bubbles: true }));
                }
                close();
            });
            cancel.addEventListener("click", close);
            modal.addEventListener("click", (event) => {
                if (event.target === modal) {
                    close();
                }
            });
        }
    };

    const bindAuditSettings = () => {
        const modal = document.querySelector("[data-audit-settings-modal]");
        if (!modal || modal.dataset.boundAuditSettings === "true") {
            return;
        }
        modal.dataset.boundAuditSettings = "true";
        const close = () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        };
        document.querySelectorAll("[data-audit-settings-open]").forEach((button) => {
            button.addEventListener("click", () => {
                modal.hidden = false;
                document.body.classList.add("modal-open");
            });
        });
        modal.querySelector("[data-audit-settings-cancel]")?.addEventListener("click", close);
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                close();
            }
        });
    };

    const bindPaletteSettings = () => {
        const modal = document.querySelector("[data-palette-settings-modal]");
        if (!modal || modal.dataset.boundPaletteSettings === "true") {
            return;
        }
        modal.dataset.boundPaletteSettings = "true";
        const close = () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        };
        const postForm = async (form, action) => {
            const response = await fetch(action, {
                method: "POST",
                body: new URLSearchParams(new FormData(form)),
                headers: {
                    "Accept": "text/html",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            });
            return response.ok;
        };
        const finishUpdate = async () => {
            close();
            await refreshMain(true);
        };
        document.querySelectorAll("[data-palette-settings-open], [data-audit-settings-open], [data-metric-settings-open]").forEach((button) => {
            button.addEventListener("click", () => {
                modal.hidden = false;
                document.body.classList.add("modal-open");
            });
        });
        modal.querySelector("[data-palette-settings-cancel]")?.addEventListener("click", close);
        modal.querySelectorAll("[data-preference-form]").forEach((form) => {
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                const submitter = event.submitter;
                const action = submitter?.formAction || form.action;
                if (!(await postForm(form, action))) {
                    return;
                }
                await finishUpdate();
            });
        });
        modal.querySelector("[data-preferences-save-all]")?.addEventListener("click", async () => {
            const forms = [...modal.querySelectorAll("[data-preference-form]")];
            const results = await Promise.all(forms.map((form) => postForm(form, form.action)));
            if (results.every(Boolean)) {
                await finishUpdate();
            }
        });
        modal.querySelector("[data-preferences-reset-all]")?.addEventListener("click", async () => {
            const forms = [...modal.querySelectorAll("[data-preference-form]")];
            const results = await Promise.all(
                forms.map((form) => postForm(form, new URL(form.dataset.resetAction, window.location.origin).href)),
            );
            if (results.every(Boolean)) {
                await finishUpdate();
            }
        });
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                close();
            }
        });
    };

    const bindFaviconUpload = () => {
        document.querySelectorAll("[data-favicon-file]").forEach((input) => {
            if (input.dataset.boundFavicon === "true") {
                return;
            }
            input.dataset.boundFavicon = "true";
            input.addEventListener("change", () => {
                const file = input.files?.[0];
                const hidden = input.closest("form")?.querySelector("[data-favicon-data]");
                if (!file || !hidden) {
                    return;
                }
                const reader = new FileReader();
                reader.addEventListener("load", () => {
                    hidden.value = String(reader.result || "");
                });
                reader.readAsDataURL(file);
            });
        });
        document.querySelectorAll("[data-backup-file]").forEach((input) => {
            if (input.dataset.boundBackup === "true") {
                return;
            }
            input.dataset.boundBackup = "true";
            input.addEventListener("change", () => {
                const file = input.files?.[0];
                const hidden = input.closest("form")?.querySelector("[data-backup-data]");
                if (!file || !hidden) {
                    return;
                }
                const reader = new FileReader();
                reader.addEventListener("load", () => {
                    hidden.value = String(reader.result || "");
                });
                reader.readAsDataURL(file);
            });
        });
    };

    const bindSignup = () => {
        const modal = document.querySelector("[data-signup-modal]");
        if (!modal || modal.dataset.boundSignup === "true") {
            return;
        }
        modal.dataset.boundSignup = "true";
        const close = () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        };
        document.querySelector("[data-signup-open]")?.addEventListener("click", () => {
            modal.hidden = false;
            document.body.classList.add("modal-open");
            modal.querySelector("input")?.focus();
        });
        modal.querySelector("[data-signup-cancel]")?.addEventListener("click", close);
        if (!modal.hidden) {
            document.body.classList.add("modal-open");
        }
    };

    const bindMetricSettings = () => {
        const modal = document.querySelector("[data-metric-settings-modal]");
        if (!modal || modal.dataset.boundMetricSettings === "true") {
            return;
        }
        modal.dataset.boundMetricSettings = "true";
        const close = () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        };
        document.querySelector("[data-metric-settings-open]")?.addEventListener("click", () => {
            modal.hidden = false;
            document.body.classList.add("modal-open");
        });
        modal.querySelector("[data-metric-settings-cancel]")?.addEventListener("click", close);
    };

    const bindPasswordConfirm = () => {
        document.querySelectorAll("form[data-password-confirm]").forEach((form) => {
            if (form.dataset.boundPasswordConfirm === "true") {
                return;
            }
            form.dataset.boundPasswordConfirm = "true";
            form.addEventListener("submit", (event) => {
                if (form.querySelector("input[name='admin_password']")) {
                    return;
                }
                event.preventDefault();
                const modal = document.querySelector("[data-password-modal]");
                const input = modal?.querySelector("[data-password-input]");
                const message = modal?.querySelector("[data-password-message]");
                if (!modal || !input || !message) {
                    return;
                }
                message.textContent = form.dataset.passwordConfirm || "Enter your password.";
                modal.hidden = false;
                document.body.classList.add("modal-open");
                input.value = "";
                input.focus();
                const close = () => {
                    modal.hidden = true;
                    document.body.classList.remove("modal-open");
                };
                modal.querySelector("[data-password-cancel]").onclick = close;
                modal.querySelector("[data-password-accept]").onclick = () => {
                    if (!input.value) {
                        input.focus();
                        return;
                    }
                    const hidden = document.createElement("input");
                    hidden.type = "hidden";
                    hidden.name = "admin_password";
                    hidden.value = input.value;
                    form.append(hidden);
                    close();
                    form.requestSubmit();
                };
            });
        });
    };

    const bindReadOnlyActions = () => {
        if (!document.body.classList.contains("read-only") || document.body.dataset.boundReadOnly === "true") {
            return;
        }
        document.body.dataset.boundReadOnly = "true";
        const modal = document.querySelector("[data-login-required-modal]");
        const open = () => {
            if (!modal) {
                window.location.assign("/login");
                return;
            }
            modal.hidden = false;
            document.body.classList.add("modal-open");
        };
        modal?.querySelector("[data-login-required-cancel]")?.addEventListener("click", () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        });
        document.addEventListener("submit", (event) => {
            const form = event.target;
            if (form.method?.toLowerCase() === "post" && !form.action.endsWith("/login") && !form.action.endsWith("/signup")) {
                event.preventDefault();
                open();
            }
        }, true);
        document.addEventListener("click", (event) => {
            const link = event.target.closest("a[href^='/edit/'], a[href^='/new']");
            if (link) {
                event.preventDefault();
                open();
            }
        }, true);
    };

    const themedConfirm = (message, confirmLabel = "Confirm") =>
        new Promise((resolve) => {
            const modal = document.querySelector("[data-confirm-modal]");
            const messageNode = modal?.querySelector("[data-confirm-message]");
            const accept = modal?.querySelector("[data-confirm-accept]");
            const cancel = modal?.querySelector("[data-confirm-cancel]");
            if (!modal || !messageNode || !accept || !cancel) {
                resolve(false);
                return;
            }
            messageNode.textContent = message;
            accept.textContent = confirmLabel;
            modal.hidden = false;
            document.body.classList.add("modal-open");
            accept.focus();

            const finish = (result) => {
                modal.hidden = true;
                document.body.classList.remove("modal-open");
                accept.removeEventListener("click", acceptAction);
                cancel.removeEventListener("click", cancelAction);
                modal.removeEventListener("click", backdropAction);
                document.removeEventListener("keydown", keyAction);
                resolve(result);
            };
            const acceptAction = () => finish(true);
            const cancelAction = () => finish(false);
            const backdropAction = (event) => {
                if (event.target === modal) {
                    finish(false);
                }
            };
            const keyAction = (event) => {
                if (event.key === "Escape") {
                    finish(false);
                }
            };
            accept.addEventListener("click", acceptAction);
            cancel.addEventListener("click", cancelAction);
            modal.addEventListener("click", backdropAction);
            document.addEventListener("keydown", keyAction);
        });

    const bindConfirmForms = () => {
        document.querySelectorAll("form[data-confirm]").forEach((form) => {
            if (form.dataset.boundConfirm === "true") {
                return;
            }
            form.dataset.boundConfirm = "true";
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                const actionPath = new URL(form.action, window.location.href).pathname;
                const confirmLabel = form.dataset.confirmAction || (actionPath.includes("/delete/") ? "Delete" : "Confirm");
                if (await themedConfirm(form.dataset.confirm || "Continue?", confirmLabel)) {
                    form.submit();
                }
            });
        });
    };

    const bindLiveServerLogs = () => {
        window.clearInterval(liveLogTimer);
        liveLogTimer = null;
        const logNodes = [...document.querySelectorAll("[data-live-server-log]")];
        if (!logNodes.length) {
            return;
        }
        const updateLogs = async () => {
            await Promise.all(
                logNodes.map(async (node) => {
                    try {
                        const limit = node.dataset.logLimit || "18";
                        const response = await fetch(`/api/server-log?limit=${encodeURIComponent(limit)}`, { cache: "no-store" });
                        if (!response.ok) {
                            return;
                        }
                        const data = await response.json();
                        const stayAtTop = node.scrollTop < 12;
                        node.textContent = data.log || "";
                        if (stayAtTop) {
                            node.scrollTop = 0;
                        }
                    } catch {
                        // Keep the last successful log snapshot visible.
                    }
                }),
            );
        };
        updateLogs();
        liveLogTimer = window.setInterval(updateLogs, 1500);
    };

    const bindServerLogSettings = () => {
        const modal = document.querySelector("[data-server-log-settings-modal]");
        if (!modal || modal.dataset.boundServerLogSettings === "true") {
            return;
        }
        modal.dataset.boundServerLogSettings = "true";
        const theme = modal.querySelector("[data-server-log-theme]");
        const background = modal.querySelector("[data-server-log-background]");
        const text = modal.querySelector("[data-server-log-text]");
        const preview = modal.querySelector("[data-server-log-theme-preview]");
        const close = () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        };
        const updatePreview = () => {
            if (!preview || !background || !text) {
                return;
            }
            preview.style.setProperty("--server-log-bg", background.value);
            preview.style.setProperty("--server-log-text", text.value);
        };
        document.querySelectorAll("[data-server-log-settings-open]").forEach((button) => {
            button.addEventListener("click", () => {
                modal.hidden = false;
                document.body.classList.add("modal-open");
            });
        });
        modal.querySelector("[data-server-log-settings-cancel]")?.addEventListener("click", close);
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                close();
            }
        });
        theme?.addEventListener("change", () => {
            const option = theme.selectedOptions[0];
            if (option?.dataset.background && option?.dataset.text) {
                background.value = option.dataset.background;
                text.value = option.dataset.text;
                updatePreview();
            }
        });
        [background, text].forEach((input) => {
            input?.addEventListener("input", () => {
                if (theme) {
                    theme.value = "custom";
                }
                updatePreview();
            });
        });
    };

    const bindAdminResult = () => {
        const modal = document.querySelector("[data-admin-result-modal]");
        if (!modal || modal.dataset.boundAdminResult === "true") {
            return;
        }
        modal.dataset.boundAdminResult = "true";
        document.body.classList.add("modal-open");
        const closeButton = modal.querySelector("[data-admin-result-close]");
        const close = () => {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        };
        closeButton?.addEventListener("click", close);
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                close();
            }
        });
        const escapeAction = (event) => {
            if (event.key === "Escape" && !modal.hidden) {
                document.removeEventListener("keydown", escapeAction);
                close();
            }
        };
        document.addEventListener("keydown", escapeAction);
        modal.querySelector("[data-copy-password]")?.addEventListener("click", async (event) => {
            const password = modal.querySelector("[data-generated-password]")?.textContent || "";
            if (!password) {
                return;
            }
            await navigator.clipboard.writeText(password);
            event.currentTarget.textContent = "Copied";
        });
        closeButton?.focus();
    };

    const bindDateShortcuts = () => {
        document.querySelectorAll("[data-expiry-months]").forEach((button) => {
            if (button.dataset.boundDateShortcut === "true") {
                return;
            }
            button.dataset.boundDateShortcut = "true";
            button.addEventListener("click", () => {
                const months = Number(button.dataset.expiryMonths || "0");
                const input = button.closest("label")?.querySelector("input[name='use_by']");
                if (!input || !months) {
                    return;
                }
                const date = new Date();
                date.setMonth(date.getMonth() + months);
                input.value = date.toISOString().slice(0, 10);
            });
        });
    };

    const bindFoodSearch = () => {
        document.querySelectorAll("[data-food-search]").forEach((input) => {
            if (input.dataset.boundFoodSearch === "true") {
                return;
            }
            input.dataset.boundFoodSearch = "true";
            const results = input.closest(".food-search")?.querySelector("[data-food-suggestions]");
            if (!results) {
                return;
            }
            let timer = null;
            let requestNumber = 0;
            const category = input.form?.querySelector("select[name='category']");
            const unit = input.form?.querySelector("select[name='unit']");
            category?.addEventListener("change", () => {
                category.dataset.userSelected = "true";
            });
            unit?.addEventListener("change", () => {
                unit.dataset.userSelected = "true";
            });

            const hideResults = () => {
                results.hidden = true;
                results.replaceChildren();
            };

            input.addEventListener("input", () => {
                window.clearTimeout(timer);
                const query = input.value.trim();
                if (!query) {
                    hideResults();
                    return;
                }
                timer = window.setTimeout(async () => {
                    const currentRequest = ++requestNumber;
                    try {
                        const [response, predictionResponse] = await Promise.all([
                            fetch(`/api/foods?q=${encodeURIComponent(query)}`, { cache: "no-store" }),
                            fetch(`/api/predict-food?q=${encodeURIComponent(query)}`, { cache: "no-store" }),
                        ]);
                        const data = await response.json();
                        const prediction = await predictionResponse.json();
                        if (currentRequest !== requestNumber) {
                            return;
                        }
                        if (category && category.dataset.userSelected !== "true" && [...category.options].some((option) => option.value === prediction.category)) {
                            category.value = prediction.category;
                        }
                        if (unit && unit.dataset.userSelected !== "true" && [...unit.options].some((option) => option.value === prediction.unit)) {
                            unit.value = prediction.unit;
                        }
                        results.replaceChildren();
                        (data.items || []).forEach((item) => {
                            const button = document.createElement("button");
                            button.type = "button";
                            button.className = "food-suggestion";
                            button.innerHTML = `<strong></strong><span></span>`;
                            button.querySelector("strong").textContent = item.name;
                            button.querySelector("span").textContent =
                                `${item.category} · ${item.unit} · latest batch ${item.batch_number}`;
                            button.addEventListener("click", () => {
                                if (!item.id) {
                                    input.value = item.name;
                                    if (category && [...category.options].some((option) => option.value === item.category)) {
                                        category.value = item.category;
                                    }
                                    if (unit && [...unit.options].some((option) => option.value === item.unit)) {
                                        unit.value = item.unit;
                                    }
                                    const freezer = input.form?.querySelector("select[name='freezer_id']");
                                    const freezerOption = freezer
                                        ? [...freezer.options].find((option) => option.textContent.trim() === item.freezer_name)
                                        : null;
                                    if (freezer && freezerOption) {
                                        freezer.value = freezerOption.value;
                                    }
                                    const selectedPeople = new Set(
                                        String(item.people_names || "")
                                            .split(",")
                                            .map((name) => name.trim().toLowerCase())
                                            .filter(Boolean),
                                    );
                                    input.form?.querySelectorAll("input[name='person_ids']").forEach((checkbox) => {
                                        const label = checkbox.closest("label")?.textContent.trim().toLowerCase();
                                        checkbox.checked = selectedPeople.has(label);
                                    });
                                    const ingredient = input.form?.querySelector("input[name='ingredient']");
                                    if (ingredient) {
                                        ingredient.checked = Boolean(item.ingredient);
                                    }
                                    const useBy = input.form?.querySelector("input[name='use_by']");
                                    if (useBy && item.use_by) {
                                        useBy.value = item.use_by;
                                    }
                                    hideResults();
                                    input.focus();
                                    return;
                                }
                                const inventoryForm = input.form?.action && new URL(input.form.action).pathname === "/";
                                const destination = inventoryForm ? "/" : "/new";
                                window.location.assign(`${destination}?copy=${item.id}&return_to=${encodeURIComponent(destination)}`);
                            });
                            results.append(button);
                        });
                        results.hidden = results.childElementCount === 0;
                    } catch {
                        hideResults();
                    }
                }, 150);
            });

            input.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    hideResults();
                }
            });
            document.addEventListener("click", (event) => {
                if (!event.target.closest(".food-search")) {
                    hideResults();
                }
            });
        });
    };

    const isEditing = () => {
        const active = document.activeElement;
        if (!active || active === document.body) {
            return false;
        }
        if (active.closest(".stock-control")) {
            return false;
        }
        return active.matches("input, textarea, select");
    };

    const refreshMain = async (force = false) => {
        if (refreshInFlight || (!force && isEditing())) {
            return;
        }
        refreshInFlight = true;
        const scrollX = window.scrollX;
        const scrollY = window.scrollY;
        const active = document.activeElement;
        const activeName = active?.getAttribute("name");
        const activeFormAction = active?.form?.getAttribute("action");
        const selectionStart = typeof active?.selectionStart === "number" ? active.selectionStart : null;
        const selectionEnd = typeof active?.selectionEnd === "number" ? active.selectionEnd : null;
        const openFilterKey = document.querySelector(".filter-dropdown[open]")?.dataset.filterKey;
        try {
            const response = await fetch(window.location.href, { headers: { "X-Requested-With": "fetch" } });
            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, "text/html");
            const nextMain = doc.querySelector("main");
            const currentMain = document.querySelector("main");
            const nextTheme = doc.querySelector("#theme-style");
            const currentTheme = document.querySelector("#theme-style");
            if (nextTheme && currentTheme) {
                currentTheme.textContent = nextTheme.textContent;
            }
            if (nextMain && currentMain) {
                currentMain.innerHTML = nextMain.innerHTML;
                bindAutoSubmit();
                bindRememberCategory();
                bindExclusiveDropdowns();
                bindUnitControls();
                bindStapleControls();
                bindQuickAdd();
                bindAuditSettings();
                bindPaletteSettings();
                bindFaviconUpload();
                bindSignup();
                bindMetricSettings();
                bindPasswordConfirm();
                bindReadOnlyActions();
                bindDateShortcuts();
                bindFoodSearch();
                bindConfirmForms();
                bindAdminResult();
                bindTableScale();
                bindLiveFilters();
                bindManualRefresh();
                bindDynamicControls();
                bindLiveServerLogs();
                bindServerLogSettings();
                if (openFilterKey) {
                    const restoredDropdown = document.querySelector(`.filter-dropdown[data-filter-key="${CSS.escape(openFilterKey)}"]`);
                    if (restoredDropdown) {
                        restoredDropdown.open = true;
                    }
                }
                if (activeName) {
                    const candidates = [...document.querySelectorAll(`[name="${CSS.escape(activeName)}"]`)];
                    const restored = candidates.find((element) => element.form?.getAttribute("action") === activeFormAction) || candidates[0];
                    restored?.focus();
                    if (selectionStart !== null && typeof restored?.setSelectionRange === "function") {
                        restored.setSelectionRange(selectionStart, selectionEnd ?? selectionStart);
                    }
                }
                window.scrollTo(scrollX, scrollY);
            }
        } finally {
            refreshInFlight = false;
        }
    };

    const bindManualRefresh = () => {
        document.querySelectorAll("[data-refresh-main]").forEach((button) => {
            if (button.dataset.boundRefreshMain === "true") {
                return;
            }
            button.dataset.boundRefreshMain = "true";
            button.addEventListener("click", async () => {
                const spinStarted = performance.now();
                button.classList.add("refreshing");
                button.disabled = true;
                try {
                    await refreshMain(true);
                } finally {
                    const replacement = document.querySelector("[data-refresh-main]");
                    if (replacement) {
                        replacement.classList.add("refreshing");
                        replacement.disabled = true;
                    }
                    const remainingSpin = Math.max(0, 700 - (performance.now() - spinStarted));
                    await new Promise((resolve) => window.setTimeout(resolve, remainingSpin));
                    (replacement || button).classList.remove("refreshing");
                    (replacement || button).disabled = false;
                }
            });
        });
    };

    const checkForUpdates = async () => {
        if (document.hidden) {
            return;
        }
        try {
            const response = await fetch("/api/version", { cache: "no-store" });
            const data = await response.json();
            if (latestVersion === null) {
                latestVersion = data.version;
                return;
            }
            if (data.version !== latestVersion) {
                latestVersion = data.version;
                await refreshMain();
            }
        } catch {
            // The next poll will try again.
        }
    };

    const bindDynamicControls = () => {
        document.querySelectorAll(".stock-control").forEach((form) => {
            if (form.dataset.boundStock === "true") {
                return;
            }
            form.dataset.boundStock = "true";
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                const button = event.submitter;
                const formData = new FormData(form);
                if (button?.name) {
                    formData.set(button.name, button.value);
                }
                const response = await fetch(form.action, {
                    method: "POST",
                    body: new URLSearchParams(formData),
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                });
                const data = await response.json().catch(() => ({}));
                if (
                    data.ask_buy &&
                    data.item_id &&
                    (await themedConfirm(`${data.item_name || "This item"} is down to 1. Add it to the Buy list?`, "Add to Buy"))
                ) {
                    const buyData = new URLSearchParams();
                    buyData.set("return_to", window.location.pathname + window.location.search);
                    await fetch(`/buy/add/${data.item_id}`, {
                        method: "POST",
                        body: buyData,
                        headers: {
                            "Accept": "application/json",
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                    });
                }
                await checkForUpdates();
                await refreshMain();
            });
        });
    };

    bindNavigation();
    bindAutoSubmit();
    bindRememberCategory();
    bindExclusiveDropdowns();
    bindUnitControls();
    bindStapleControls();
    bindQuickAdd();
    bindAuditSettings();
    bindPaletteSettings();
    bindFaviconUpload();
    bindSignup();
    bindMetricSettings();
    bindPasswordConfirm();
    bindReadOnlyActions();
    bindDateShortcuts();
    bindFoodSearch();
    bindConfirmForms();
    bindAdminResult();
    bindTableScale();
    bindLiveFilters();
    bindManualRefresh();
    bindDynamicControls();
    bindLiveServerLogs();
    bindServerLogSettings();
    checkForUpdates();
    window.setInterval(checkForUpdates, 4000);
})();
