(function () {
    if (window.appModalInitialized) return;
    window.appModalInitialized = true;

    const focusableSelector = [
        'a[href]',
        'button:not([disabled])',
        'input:not([disabled])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])'
    ].join(',');

    let activeModal = null;
    let lastModalTrigger = null;
    let inertedElements = [];

    function getModal(name) {
        return document.querySelector(
            `[data-modal="${name}"]`
        );
    }

    function getDialog(modal) {
        return modal?.querySelector(
            '[data-modal-dialog]'
        );
    }

    function getFocusableElements(modal) {
        const dialog = getDialog(modal);

        if (!dialog) return [];

        return Array.from(
            dialog.querySelectorAll(
                focusableSelector
            )
        ).filter(function (element) {
            return (
                !element.disabled &&
                element.offsetParent !== null
            );
        });
    }

    function moveModalToBody(modal) {
        if (
            modal &&
            modal.parentElement !== document.body
        ) {
            document.body.appendChild(modal);
        }
    }

    function inertBackground(modal) {
        inertedElements =
            Array.from(document.body.children)
                .filter(function (element) {
                    return element !== modal;
                })
                .map(function (element) {
                    return {
                        element,
                        inert: element.inert
                    };
                });

        inertedElements.forEach(function (item) {
            item.element.inert = true;
        });
    }

    function restoreBackground() {
        inertedElements.forEach(function (item) {
            item.element.inert = item.inert;
        });

        inertedElements = [];
    }

    function openModal(name, trigger) {
        const modal = getModal(name);
        const dialog = getDialog(modal);

        if (!modal || !dialog) return;

        /*
          Give feature-specific code a chance to prepare
          the modal before it becomes visible.
        */
        modal.dispatchEvent(
            new CustomEvent(
                'modal:beforeopen',
                {
                    bubbles: true,
                    detail: { trigger }
                }
            )
        );

        lastModalTrigger =
            trigger || document.activeElement;

        moveModalToBody(modal);

        modal.hidden = false;
        activeModal = modal;

        document.body.classList.add(
            'modal-open'
        );

        inertBackground(modal);

        const autofocus =
            modal.querySelector(
                '[data-modal-autofocus]'
            );

        if (autofocus) {
            autofocus.focus({
                preventScroll: true
            });
        } else {
            dialog.focus({
                preventScroll: true
            });
        }

        modal.dispatchEvent(
            new CustomEvent(
                'modal:opened',
                { bubbles: true }
            )
        );
    }

    function closeModal(modal = activeModal) {
        if (!modal || modal.hidden) return;

        modal.hidden = true;

        document.body.classList.remove(
            'modal-open'
        );

        restoreBackground();

        modal.dispatchEvent(
            new CustomEvent(
                'modal:closed',
                { bubbles: true }
            )
        );

        if (
            lastModalTrigger &&
            typeof lastModalTrigger.focus ===
            'function'
        ) {
            lastModalTrigger.focus({
                preventScroll: true
            });
        }

        activeModal = null;
        lastModalTrigger = null;
    }

    function closeModalByName(name) {
        closeModal(getModal(name));
    }

    document.addEventListener(
        'click',
        function (event) {
            const openButton =
                event.target.closest(
                    '[data-modal-open]'
                );

            if (openButton) {
                openModal(
                    openButton.dataset.modalOpen,
                    openButton
                );

                return;
            }

            const closeButton =
                event.target.closest(
                    '[data-modal-close]'
                );

            if (closeButton) {
                closeModal(
                    closeButton.closest(
                        '[data-modal]'
                    )
                );

                return;
            }

            if (
                activeModal &&
                event.target === activeModal
            ) {
                closeModal(activeModal);
            }
        }
    );

    document.addEventListener(
        'keydown',
        function (event) {
            if (!activeModal) return;

            if (event.key === 'Escape') {
                event.preventDefault();
                closeModal(activeModal);
                return;
            }

            if (event.key !== 'Tab') {
                return;
            }

            const focusable =
                getFocusableElements(
                    activeModal
                );

            if (!focusable.length) {
                event.preventDefault();

                getDialog(activeModal)
                    ?.focus();

                return;
            }

            const first = focusable[0];

            const last =
                focusable[
                focusable.length - 1
                ];

            if (
                event.shiftKey &&
                document.activeElement === first
            ) {
                event.preventDefault();
                last.focus();
                return;
            }

            if (
                !event.shiftKey &&
                document.activeElement === last
            ) {
                event.preventDefault();
                first.focus();
            }
        }
    );

    /*
      Small public API for feature code that needs to
      close a modal programmatically.
    */
    window.appModal = {
        open: openModal,
        close: closeModalByName
    };
})();