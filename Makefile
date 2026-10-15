VERSION := 0.1

# Directories
SRCDIR   := src
BUILDDIR := build
BINDIR   := bin
DOCDIR   := docs

TARGET := $(BINDIR)/barnsley_fern
OUTPUT := $(BUILDDIR)/fern.ppm

# Graphics subsystem: GRAPHICS=1 (default) or GRAPHICS=0 (headless).
GRAPHICS ?= 1

CXX      ?= g++
CXXFLAGS := -O3 -Wall -Wextra -std=c++11
CPPFLAGS :=
LDFLAGS  :=
LDLIBS   :=

ifeq ($(GRAPHICS),1)
CPPFLAGS += -DENABLE_GRAPHICS=1
else
CPPFLAGS += -DENABLE_GRAPHICS=0
endif

CPPFLAGS += -DPROJECT_VERSION='"$(VERSION)"'

SRCS := $(SRCDIR)/main.cpp
OBJS := $(BUILDDIR)/main.o
DEPS := $(OBJS:.o=.d)
BUILDCFG := $(BUILDDIR)/.buildcfg

RM    := rm -f
RMDIR := rm -rf
MKDIR := mkdir -p

.PHONY: all run test test-headless clean distclean help FORCE

all: $(TARGET)

$(TARGET): $(OBJS) | $(BINDIR)
	$(CXX) $(LDFLAGS) $(OBJS) -o $@ $(LDLIBS)

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

run: $(TARGET)
	./$(TARGET) --out $(OUTPUT)

test: $(TARGET)
	$(RM) $(OUTPUT)
	./$(TARGET) --out $(OUTPUT)
	@test -s $(OUTPUT) || { echo "FAIL: $(OUTPUT) not created"; exit 1; }
	@head -n 1 $(OUTPUT) | grep -qx "P3" || { echo "FAIL: invalid PPM header"; exit 1; }
	@grep -q "34 139 34" $(OUTPUT) || { echo "FAIL: no rendered pixels"; exit 1; }
	@echo "PASS: $(OUTPUT) generated and validated"

# Verify the build without the graphics subsystem.
test-headless:
	$(MAKE) GRAPHICS=0 $(TARGET)
	$(RM) $(OUTPUT)
	@./$(TARGET) --out $(OUTPUT) > /dev/null
	@test ! -e $(OUTPUT) || { echo "FAIL: headless build produced $(OUTPUT)"; exit 1; }
	@./$(TARGET) | grep -q "GRAPHICS=0" || { echo "FAIL: headless mode not reported"; exit 1; }
	@echo "PASS: headless build produces no image"

clean:
	$(RMDIR) $(BUILDDIR)

distclean: clean
	$(RMDIR) $(BINDIR)

help:
	@echo "Directories: $(SRCDIR)/ (sources), $(BUILDDIR)/ (objects, $(OUTPUT)), $(BINDIR)/ (binary), $(DOCDIR)/ (changelog), README.asciidoc at root"
	@echo "Targets:"
	@echo "  all            Build $(TARGET) (default)"
	@echo "  run            Build and run"
	@echo "  test           Build, run and validate $(OUTPUT)"
	@echo "  test-headless  Build with GRAPHICS=0 and verify no image is produced"
	@echo "  clean          Remove the build directory $(BUILDDIR)/"
	@echo "  distclean      clean + remove $(BINDIR)/"
	@echo "  help           Show this help"
