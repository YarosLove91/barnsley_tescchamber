#include <iostream>
#include <vector>
#include <chrono>
#include <thread>
#include <cstdlib>
#include <ctime>

using std::cout;
using std::cin;
using std::vector;
using std::pair;
using std::flush;

// Global grid dimensions (optimized for the Gosper Glider Gun pattern)
const int HEIGHT = 30;
const int WIDTH = 60;

  class GameOfLife {
  private:
      vector<vector<bool>> grid;

      // Counts the number of living neighbors around the cell (x, y)
      // The grid wraps around borders behaving like a torus
      int count_neighbors(int x, int y) {
        int count = 0;
        for (int i = -1; i <= 1; ++i) {
          for (int j = -1; j <= 1; ++j) {
            if (i == 0 && j == 0) continue; // Skip the cell itself

            // Toroidal grid logic (wraps edges around)
            int nx = (x + i + HEIGHT) % HEIGHT;
            int ny = (y + j + WIDTH) % WIDTH;

            if (grid[nx][ny]) {
              count++;
            }
          }
        }
      return count;
    }

  public:
    GameOfLife() {
      grid.assign(HEIGHT, vector<bool>(WIDTH, false));
    }

    // MODE 1: Randomly populates the grid based on a target density percentage
    void init_random(int density_percent = 25) {
      // Seed the random number generator with the current time
      std::srand(static_cast<unsigned int>(std::time(nullptr)));

      for (int i = 0; i < HEIGHT; ++i) {
        for (int j = 0; j < WIDTH; ++j) {
            // Populate cell based on the specified probability
            grid[i][j] = (std::rand() % 100) < density_percent;
        }
      }
    }

    // MODE 2: Spawns the iconic "Gosper Glider Gun" – an infinite glider generator
    void init_gosper_gun() {
      grid.assign(HEIGHT, vector<bool>(WIDTH, false));

      // Offset coordinates to position the gun nicely on the grid
      int r = 2;
      int c = 2;

      // Predefined coordinates for the Gosper Glider Gun pattern
      vector<pair<int, int>> dots = {
        {r+4, c+0}, {r+4, c+1}, {r+5, c+0}, {r+5, c+1}, // Left static block
        {r+4, c+10}, {r+5, c+10}, {r+6, c+10},
        {r+3, c+11}, {r+7, c+11},
        {r+2, c+12}, {r+2, c+13}, {r+8, c+12}, {r+8, c+13},
        {r+5, c+14},
        {r+3, c+15}, {r+7, c+15},
        {r+4, c+16}, {r+5, c+16}, {r+6, c+16},
        {r+5, c+17}, // Left moving/oscillating engine structure
        {r+2, c+20}, {r+3, c+20}, {r+4, c+20},
        {r+2, c+21}, {r+3, c+21}, {r+4, c+21},
        {r+1, c+22}, {r+5, c+22},
        {r+0, c+24}, {r+1, c+24}, {r+5, c+24}, {r+6, c+24}, // Right engine structure
        {r+2, c+34}, {r+3, c+34}, {r+2, c+35}, {r+3, c+35}  // Right static block
      };

      for (const auto& dot : dots) {
        if (dot.first < HEIGHT && dot.second < WIDTH) {
          grid[dot.first][dot.second] = true;
        }
      }
    }

    // Evaluates Conway's Game of Life rules to compute the next generation
    void update() {
        vector<vector<bool>> next_grid = grid;

        for (int i = 0; i < HEIGHT; ++i) {
          for (int j = 0; j < WIDTH; ++j) {
            int neighbors = count_neighbors(i, j);

            if (grid[i][j]) {
            // Rule 1 & 3: Underpopulation or Overpopulation causes death
              if (neighbors < 2 || neighbors > 3) {
                next_grid[i][j] = false;
              }
            } else {
              // Rule 4: Reproduction (exactly 3 neighbors creates life)
              if (neighbors == 3) {
                next_grid[i][j] = true;
              }
            }
          }
        }
      grid = next_grid;
    }

      // Renders the board into the console window
      void draw(int generation) {
      // Cross-platform screen clearing
  #ifdef _WIN32
        std::system("cls");
  #else
        std::system("clear");
  #endif
        cout << "Generation: " << generation << "\n";
        for (int i = 0; i < HEIGHT; ++i) {
          for (int j = 0; j < WIDTH; ++j) {
            // Live cell is represented by '#', dead cell is a space
            cout << (grid[i][j] ? '#' : ' ');
          }
          cout << '\n';
        }
      cout << flush;
    }
  };

  int main() {
    GameOfLife game;

    // Simple console user interface for mode selection
    cout << "Select starting mode:\n";
    cout << "1. Random Chaos\n";
    cout << "2. Gosper Glider Gun\n";
    cout << "Your choice (1 or 2): ";

    int choice = 1;
    cin >> choice;

    if (choice == 2) {
      game.init_gosper_gun();
    } else {
      game.init_random(25); // Starts with ~25% grid fill rate
    }

    int generation = 0;

    // Main simulation loop
    while (true) {
      game.draw(generation++);
      game.update();

      // Pause execution for 80 milliseconds per frame to slow down the speed
      std::this_thread::sleep_for(std::chrono::milliseconds(80));
    }

    return 0;
  }
