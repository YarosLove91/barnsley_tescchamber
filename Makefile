VERSION := 0.1

# Directories
SRCDIR   := src
BUILDDIR := build
BINDIR   := bin
DOCDIR   := docs

# Programs built from src/ (source file -> binary)
FERN_BIN   := $(BINDIR)/barnsley_fern
A5_1_BIN   := $(BINDIR)/a5_1
CONWAY_BIN := $(BINDIR)/conway

OUTPUT := $(BUILDDIR)/fern.ppm

# Graphics subsystem of the fern generator: GRAPHICS=1 (default) or GRAPHICS=0 (headless).
GRAPHICS ?= 1

CXX      ?= g++
CXXFLAGS := -O3 -Wall -Wextra -std=c++11 -pthread
CPPFLAGS :=
LDFLAGS  :=
LDLIBS   := -pthread

ifeq ($(GRAPHICS),1)
CPPFLAGS += -DENABLE_GRAPHICS=1
else
CPPFLAGS += -DENABLE_GRAPHICS=0
endif

CPPFLAGS += -DPROJECT_VERSION='"$(VERSION)"'

OBJS := $(BUILDDIR)/main.o $(BUILDDIR)/A5_1.o $(BUILDDIR)/conway.o
DEPS := $(OBJS:.o=.d)
BUILDCFG := $(BUILDDIR)/.buildcfg

RM    := rm -f
RMDIR := rm -rf
MKDIR := mkdir -p

.PHONY: all run run-fern run-a5_1 run-conway run-all test test-headless clean distclean help FORCE

all: $(FERN_BIN) $(A5_1_BIN) $(CONWAY_BIN)

$(FERN_BIN): $(BUILDDIR)/main.o | $(BINDIR)
	$(CXX) $(LDFLAGS) $< -o $@ $(LDLIBS)

$(A5_1_BIN): $(BUILDDIR)/A5_1.o | $(BINDIR)
	$(CXX) $(LDFLAGS) $< -o $@ $(LDLIBS)

$(CONWAY_BIN): $(BUILDDIR)/conway.o | $(BINDIR)
	$(CXX) $(LDFLAGS) $< -o $@ $(LDLIBS)

$(BUILDDIR) $(BINDIR):
	$(MKDIR) $@

# Rebuild when flags change (e.g. GRAPHICS=0/1).
$(BUILDCFG): FORCE | $(BUILDDIR)
	@echo '$(CPPFLAGS) $(CXXFLAGS)' > $@.tmp
	@if cmp -s $@.tmp $@; then $(RM) $@.tmp; else mv $@.tmp $@; fi

FORCE:

$(OBJS): $(BUILDCFG)

$(BUILDDIR)/%.o: $(SRCDIR)/%.cpp | $(BUILDDIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@

-include $(DEPS)

run: run-fern

run-fern: $(FERN_BIN)
	./$(FERN_BIN) --out $(OUTPUT)

run-a5_1: $(A5_1_BIN)
	./$(A5_1_BIN)

# Interactive animation (Ctrl-C to stop).
run-conway: $(CONWAY_BIN)
	./$(CONWAY_BIN)

run-all: run-fern run-a5_1 run-conway

test: $(FERN_BIN)
	$(RM) $(OUTPUT)
	./$(FERN_BIN) --out $(OUTPUT)
	@test -s $(OUTPUT) || { echo "FAIL: $(OUTPUT) not created"; exit 1; }
	@head -n 1 $(OUTPUT) | grep -qx "P3" || { echo "FAIL: invalid PPM header"; exit 1; }
	@grep -q "34 139 34" $(OUTPUT) || { echo "FAIL: no rendered pixels"; exit 1; }
	@echo "PASS: $(OUTPUT) generated and validated"

# Verify the fern build without the graphics subsystem.
test-headless:
	$(MAKE) GRAPHICS=0 $(FERN_BIN)
	$(RM) $(OUTPUT)
	@./$(FERN_BIN) --out $(OUTPUT) > /dev/null
	@test ! -e $(OUTPUT) || { echo "FAIL: headless build produced $(OUTPUT)"; exit 1; }
	@./$(FERN_BIN) | grep -q "GRAPHICS=0" || { echo "FAIL: headless mode not reported"; exit 1; }
	@echo "PASS: headless build produces no image"

clean:
	$(RMDIR) $(BUILDDIR)

distclean: clean
	$(RMDIR) $(BINDIR)

help:
	@echo "Directories: $(SRCDIR)/ (sources), $(BUILDDIR)/ (objects, $(OUTPUT)), $(BINDIR)/ (binaries), $(DOCDIR)/ (changelog), README.asciidoc at root"
	@echo "Programs: $(notdir $(FERN_BIN)) (main.cpp), $(notdir $(A5_1_BIN)) (A5_1.cpp), $(notdir $(CONWAY_BIN)) (conway.cpp)"
	@echo "Targets:"
	@echo "  all            Build all programs (default)"
	@echo "  run / run-fern Run $(notdir $(FERN_BIN)) (writes $(OUTPUT))"
	@echo "  run-a5_1       Run $(notdir $(A5_1_BIN))"
	@echo "  run-conway     Run $(notdir $(CONWAY_BIN)) (interactive, Ctrl-C to stop)"
	@echo "  run-all        Run all three"
	@echo "  test           Build, run and validate $(OUTPUT)"
	@echo "  test-headless  Build fern with GRAPHICS=0 and verify no image is produced"
	@echo "  clean          Remove the build directory $(BUILDDIR)/"
	@echo "  distclean      clean + remove $(BINDIR)/"
	@echo "  help           Show this help"
