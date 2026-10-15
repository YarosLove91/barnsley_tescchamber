#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <cstdlib>
#include <ctime>

// ---------------------------------------------------------------------------
// Graphics subsystem.
// Enabled/disabled at build time:
//     make GRAPHICS=1   -> -DENABLE_GRAPHICS=1  (default)
//     make GRAPHICS=0   -> -DENABLE_GRAPHICS=0  (headless, no image output)
// When built with graphics it can be toggled at runtime:
//     --graphics / --no-graphics, plus terminal preview --preview.
// No external dependencies: rasterization and PPM/terminal output are built in.
// ---------------------------------------------------------------------------
#ifndef ENABLE_GRAPHICS
#define ENABLE_GRAPHICS 1
#endif

#ifndef PROJECT_VERSION
#define PROJECT_VERSION "0.1"
#endif

  using std::cout;
  using std::endl;
  using std::cerr;
  using std::vector;

  // Point coordinates
  struct Point {
    double x, y;
  };

  struct Options {
    int iterations = 500000;
    int width      = 600;
    int height     = 1000;
    std::string output = "fern.ppm";
    bool graphics  = ENABLE_GRAPHICS != 0;
    bool preview   = false;
    bool help      = false;
    bool version   = false;
};

  static void printHelp(const char* prog) {
    cout  << "Usage: " << prog << " [options]\n"
          << "  --graphics          enable the graphics subsystem\n"
          << "  --no-graphics       disable the graphics subsystem (headless)\n"
          << "  --preview           print an ASCII preview of the fractal\n"
          << "  --out FILE          PPM output file (default fern.ppm)\n"
          << "  --iterations N      number of iterations (default 200000)\n"
          << "  --width N           image width (default 600)\n"
        << "  --height N          image height (default 1000)\n"
        << "  --version           show version and exit\n"
        << "  -h, --help          show this help\n";
}

static void printVersion() {
    std::cout << "barnsley_fern " << PROJECT_VERSION << "\n";
}

  static int parseArgs(int argc, char** argv, Options& opt) {
    for (int i = 1; i < argc; ++i) {
      std::string a = argv[i];

        if (a == "--help" || a == "-h") {
            opt.help = true;
        } else if (a == "--version") {
            opt.version = true;
        } else if (a == "--no-graphics") {
        opt.graphics = false;
      } else if (a == "--graphics") {
  #if ENABLE_GRAPHICS
      opt.graphics = true;
  #else
      cerr << "Warning: graphics subsystem not built (make GRAPHICS=1)\n";
  #endif
      } else if (a == "--preview") {
  #if ENABLE_GRAPHICS
    opt.preview = true;
  #else
    cerr << "Warning: graphics subsystem not built (make GRAPHICS=1)\n";
  #endif
      } else if (a == "--out" && i + 1 < argc) {
        opt.output = argv[++i];
      } else if (a == "--iterations" && i + 1 < argc) {
        opt.iterations = std::atoi(argv[++i]);
      } else if (a == "--width" && i + 1 < argc) {
        opt.width = std::atoi(argv[++i]);
      } else if (a == "--height" && i + 1 < argc) {
        opt.height = std::atoi(argv[++i]);
      } else {
        cerr << "Unknown argument: " << a << "\n";
        return 2;
      }
    }
    return 0;
  }

  // Iterated function system points (4 affine transforms)
  static vector<Point> generateFern(int iterations) {
    vector<Point> points;
    points.reserve(static_cast<size_t>(iterations));

    double x = 0.0;
    double y = 0.0;

    for (int i = 0; i < iterations; ++i) {
      double r = static_cast<double>(std::rand()) / RAND_MAX;
      double next_x, next_y;

      // 1. Stem (probability 1%)
      if (r < 0.01) {
        next_x = 0.0;
        next_y = 0.16 * y;
      }
      // 2. Small inner leaflets (probability 85%)
      else if (r < 0.86) {
        next_x = 0.85 * x + 0.04 * y;
        next_y = -0.04 * x + 0.85 * y + 1.6;
      }
      // 3. Left side leaves (probability 7%)
      else if (r < 0.93) {
        next_x = 0.2 * x - 0.26 * y;
        next_y = 0.23 * x + 0.22 * y + 1.6;
      }
      // 4. Right side leaves (probability 7%)
      else {
        next_x = -0.15 * x + 0.28 * y;
        next_y = 0.26 * x + 0.24 * y + 0.44;
      }

      x = next_x;
      y = next_y;
      points.push_back({x, y});
    }
    return points;
  }

  #if ENABLE_GRAPHICS
  // RGB raster image and its output - this is the graphics subsystem.
  class RasterImage {
  public:
    RasterImage(int w, int h)
        : w_(w), h_(h), data_(static_cast<size_t>(w) * h * 3, 0) {}

    void draw(const vector<Point>& points) {
      for (const Point& p : points) {
        // Map mathematical fractal coordinates to pixels.
        // Mathematical x is roughly in [-2.182, 2.656],
        // mathematical y is roughly in [0, 9.998].
        int px = static_cast<int>((p.x + 2.5) * (w_ / 5.0));
        int py = static_cast<int>((10.0 - p.y) * (h_ / 10.0)); // flip Y axis
        if (px >= 0 && px < w_ && py >= 0 && py < h_) {
          set(px, py, 34, 139, 34); // forest green
        }
      }
    }

    long coloredPixels() const {
      long count = 0;
      for (size_t i = 1; i < data_.size(); i += 3) {
        if (data_[i] != 0) ++count;
      }
      return count;
    }

  // ASCII preview - graphics output without external libraries.
  void preview(std::ostream& os, int cols = 100, int rows = 40) const {
    for (int ry = 0; ry < rows; ++ry) {
      int y0 = ry * h_ / rows;
      int y1 = (ry + 1) * h_ / rows;

      for (int rx = 0; rx < cols; ++rx) {
        int x0 = rx * w_ / cols;
        int x1 = (rx + 1) * w_ / cols;
        bool on = false;
          for (int yy = y0; yy < y1 && !on; ++yy) {
            for (int xx = x0; xx < x1; ++xx) {
                if (data_[(static_cast<size_t>(yy) * w_ + xx) * 3 + 1] != 0) {
                  on = true;
                  break;
                }
            }
          }
          os << (on ? '#' : ' ');
        }
      os << '\n';
    }
  }

    // Write to PPM (P3 - plain text format).
    bool savePPM(const std::string& path) const {
        std::ofstream out(path);
        if (!out) {
            cerr << "Failed to create file: " << path << "\n";
            return false;
        }
        out << "P3\n" << w_ << " " << h_ << "\n255\n";
        for (int r = 0; r < h_; ++r) {
            for (int c = 0; c < w_; ++c) {
                const unsigned char* p = &data_[(static_cast<size_t>(r) * w_ + c) * 3];
                if (p[1] != 0) {
                    out << "34 139 34 ";  // leaf
                } else {
                    out << "0 0 0 ";      // background
                }
            }
            out << "\n";
        }
        return static_cast<bool>(out);
    }

  private:
    void set(int x, int y, unsigned char r, unsigned char g, unsigned char b) {
      unsigned char* p = &data_[(static_cast<size_t>(y) * w_ + x) * 3];
      p[0] = r;
      p[1] = g;
      p[2] = b;
    }

    int w_, h_;
    vector<unsigned char> data_;
  };
#endif

  int main(int argc, char** argv) {
    Options opt;

    if (int rc = parseArgs(argc, argv, opt)) {
      return rc;
    }
    if (opt.version) {
        printVersion();
        return 0;
    }
    if (opt.help) {
        printHelp(argv[0]);
        return 0;
    }
    if (opt.iterations <= 0 || opt.width <= 0 || opt.height <= 0) {
      cerr << "Error: --iterations, --width and --height must be positive\n";
      return 1;
    }

    // Seed the random number generator
    std::srand(static_cast<unsigned int>(std::time(nullptr)));

    const vector<Point> points = generateFern(opt.iterations);
    cout << "Iterations: " << points.size() << "\n";

  #if ENABLE_GRAPHICS
    if (opt.graphics) {
      RasterImage image(opt.width, opt.height);
      image.draw(points);

      if (opt.preview) {
        image.preview(cout);
      }

      if (!image.savePPM(opt.output)) {
        return 1;
      }
      cout << "File '" << opt.output << "' created successfully. "
            << "Open it to view the fractal.\n";
      cout << "Green pixels: " << image.coloredPixels() << "\n";
    } else {
        cout << "Graphics subsystem disabled (--no-graphics): "
                  << "no image is produced.\n";
    }
  #else
    cout << "Built without the graphics subsystem (GRAPHICS=0): "
        << "no image is produced.\n";
  #endif

    return 0;
  }
