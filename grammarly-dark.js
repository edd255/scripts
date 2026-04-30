(() => {
    const id = "grammarly-dark-toggle";
    const old = document.getElementById(id);
    if (old) {
        old.remove();
        return;
    }
    const style = document.createElement("style");
    style.id = id;
    style.textContent = `
        html {
            background: #111 !important;
            filter: invert(1) hue-rotate(180deg) brightness(0.95) contrast(0.9) !important;
        }

        img,
        video,
        picture,
        canvas,
        svg,
        iframe {
            filter: invert(1) hue-rotate(180deg) !important;
        }

        ::selection {
            background: #3b82f6 !important;
            color: #fff !important;
        }
`;
    document.head.appendChild(style);
})();
