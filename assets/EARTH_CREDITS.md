# Earth imagery credits

Kaatopaikka Capital's **Overview** globe uses self-hosted global
satellite-composite imagery, not a live camera or live meteorology feed.

- **Day surface:** `assets/earth-blue-marble-day.jpg`
- **Night-side light visualization:** `assets/earth-city-lights.jpg`
- **Cloud composite:** `assets/earth-cloud-cover.png`

These textures were sourced from the [Three.js example textures](https://github.com/mrdoob/three.js/tree/dev/examples/textures/planets).
The global Earth imagery derives from NASA Goddard Space Flight Center
visualizations, including **Blue Marble**, Reto Stöckli and Robert Simmon.
Credits: **NASA / Goddard Space Flight Center / Scientific Visualization Studio**.

NASA Blue Marble material:
https://svs.gsfc.nasa.gov/2915

The texture composite illustrates geographically accurate visible geography,
city-light concentrations and cloud coverage. **It is not a 2024–2026 time
series of actual weather, storms or nighttime electrical consumption.**
The astronomy calculations for day/night orientation, by contrast, respond
to the selected date and the accelerated simulation clock.

The site draws the globe entirely using locally bundled image files with
WebGL acceleration where supported and a separate Canvas 2D fallback.
No external rendering library or streaming texture service is necessary.
