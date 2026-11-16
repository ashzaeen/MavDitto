"""Hand-built HTML fixtures, so extraction is tested without touching the network."""

# A realistic university page: content wrapped in <main>, surrounded by chrome
# that must not leak into the counts, plus a lazy-loaded image and a PDF link.
UNIVERSITY_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <title>Undergraduate Admissions | Example University</title>
  <meta property="og:title" content="Undergraduate Admissions">
</head>
<body>
  <header class="site-header">
    <nav class="main-nav">
      <a href="/">Home</a>
      <a href="/academics">Academics</a>
      <img src="/img/logo.png">
    </nav>
  </header>
  <div id="breadcrumb"><a href="/admissions">Admissions</a></div>
  <main>
    <h1>Undergraduate Admissions</h1>
    <p>Applications for the fall semester are due by March 1. The application
       fee is $75 and is non-refundable once submitted to the university.</p>
    <h2>Requirements</h2>
    <p>Freshman applicants must submit official high school transcripts and
       demonstrate a minimum 3.0 grade point average on a four point scale.</p>
    <img src="/img/campus.jpg" alt="Students walking across the campus lawn">
    <img data-src="/img/library.jpg">
    <h3>Deadlines</h3>
    <p>Priority consideration closes on February 15 for scholarship review.</p>
    <ul>
      <li><a href="/docs/checklist.pdf">Application checklist (PDF)</a></li>
      <li><a href="https://external.example.org/testing">Testing information</a></li>
      <li><a href="mailto:admissions@example.edu">Email us</a></li>
      <li><a href="#top">Back to top</a></li>
    </ul>
  </main>
  <aside class="sidebar"><a href="/related">Related programs</a></aside>
  <footer class="site-footer">
    <a href="/privacy">Privacy</a>
    <img src="/img/seal.png" alt="University seal">
  </footer>
</body>
</html>
"""

# Same page, migrated badly: the fee sentence and the GPA requirement are gone,
# the Deadlines section is missing, one image lost its alt text, and the PDF
# link was dropped. This is the synthetic worst-case pair from the build plan.
UNIVERSITY_PAGE_DEGRADED = """
<!doctype html>
<html lang="en">
<head><title>Undergraduate Admissions - Example University</title></head>
<body>
  <header class="site-header"><nav><a href="/">Home</a></nav></header>
  <div class="entry-content">
    <h1>Undergraduate Admissions</h1>
    <p>Applications for the fall semester are due by March 1. We look forward
       to reviewing your materials and welcoming you to our community soon.</p>
    <h2>Requirements</h2>
    <p>Freshman applicants must submit official high school transcripts as part
       of a complete application package for review by our admissions staff.</p>
    <img src="/img/campus.jpg">
    <ul>
      <li><a href="https://external.example.org/testing">Testing information</a></li>
    </ul>
  </div>
  <footer class="site-footer"><a href="/privacy">Privacy</a></footer>
</body>
</html>
"""

# No landmark element at all -- exercises the readability/body fallback path.
NO_LANDMARK_PAGE = """
<!doctype html>
<html><head><title>Policy Update</title></head>
<body>
  <div class="nav-wrapper"><a href="/">Home</a></div>
  <div>
    <h2>Parking Policy Update</h2>
    <p>Effective September 1, permit holders must display the decal on the rear
       windshield. Vehicles without a visible decal may be cited by campus
       police, and repeated violations can result in the permit being revoked
       for the remainder of the academic year without a refund.</p>
    <p>Questions about the change should be directed to the parking office,
       which is open weekdays from eight in the morning until five.</p>
  </div>
</body></html>
"""

# A JS shell: almost no text until a browser runs the scripts.
JS_SHELL_PAGE = """
<!doctype html>
<html><head><title>Loading</title></head>
<body><div id="root"></div><script>window.boot();</script></body></html>
"""

# Sitecore-style page: hero and section artwork live in CSS background-image
# rather than <img>, which is how the real uta.edu pages are built.
SITECORE_BACKGROUND_PAGE = """
<!doctype html>
<html><head><title>Research at Example</title></head>
<body>
  <main>
    <div class="hero" style="background-image: url('/-/media/hero.jpg?rev=abc')">
      <h1>Research</h1>
    </div>
    <p>Our faculty secured forty two million dollars in external research
       funding last year across engineering, nursing and the sciences.</p>
    <div class="panel" style="background:#fff url(/-/media/lab.png) no-repeat">
      <h2>Facilities</h2>
      <p>The shared instrumentation core is open to all graduate students who
         have completed the required laboratory safety training module.</p>
    </div>
    <img src="/img/team.jpg" alt="The research team in the lab">
  </main>
</body></html>
"""

# A real pattern from a Notion-backed site: the whole page sits inside an
# element whose class carries a *state* modifier ("this page has a footer"),
# and the page title lives in a block named "header".
STATE_CLASS_PAGE = """
<!doctype html>
<html><head><title>High School Site</title></head>
<body>
  <div class="notion-header__title-wrapper">
    <h1 class="notion-header__title">High School Site</h1>
  </div>
  <nav class="nav-bar"><a href="/elsewhere">Elsewhere</a></nav>
  <main>
    <article class="notion-root max-width has-footer">
      <h1>Hello, Welcome!</h1>
      <p>I am a budding programmer, occasional wordsmith and an avid reader of
         long form technology writing, with a deep interest in business.</p>
      <h2>Experiences</h2>
      <p>High school was a whirlwind of exciting opportunities, and I lent my
         skills to several organizations over the course of four years.</p>
      <img src="/img/robotics.jpg" alt="The robotics team">
      <a href="/projects">Projects</a>
    </article>
  </main>
  <footer class="site-footer"><a href="/privacy">Privacy</a></footer>
</body></html>
"""
