CXX ?= g++
SST_BIN ?= /data/feiyang/sst/bin
SST_CONFIG := $(SST_BIN)/sst-config
SST_CXXFLAGS := $(shell $(SST_CONFIG) --ELEMENT_CXXFLAGS)
DRAMSIM3_ROOT ?= $(SPINE_IDLE_DRAMSIM3_SRC)

ROOT := ../..
BUILD_DIR ?= $(ROOT)/build/sst
PGO_MODE ?= off
PGO_PROFILE_DIR ?= $(BUILD_DIR)/pgo-data
NATIVE_HOST ?= 0

ifeq ($(NATIVE_HOST),0)
SPINE_HOST_ARCH_FLAGS ?=
else ifeq ($(NATIVE_HOST),1)
SPINE_HOST_ARCH_FLAGS ?= -march=native -fno-semantic-interposition
else
$(error unsupported NATIVE_HOST '$(NATIVE_HOST)'; expected 0 or 1)
endif

ifeq ($(PGO_MODE),off)
SPINE_HOST_OPT_FLAGS ?= -O3 -DNDEBUG -flto
else ifeq ($(PGO_MODE),generate)
SPINE_HOST_OPT_FLAGS ?= -O3 -DNDEBUG -fprofile-generate=$(abspath $(PGO_PROFILE_DIR))
else ifeq ($(PGO_MODE),use)
SPINE_HOST_OPT_FLAGS ?= -O3 -DNDEBUG -fprofile-use=$(abspath $(PGO_PROFILE_DIR)) -fprofile-correction -flto
else
$(error unsupported PGO_MODE '$(PGO_MODE)'; expected off, generate, or use)
endif

TARGET := $(BUILD_DIR)/libspine_cycle.so
INCLUDES := -I$(ROOT)/cpp/include
CXXFLAGS := $(SST_CXXFLAGS) -std=c++20 $(SPINE_HOST_OPT_FLAGS) \
            $(SPINE_HOST_ARCH_FLAGS) -fPIC \
            -Wall -Wextra -Wpedantic $(INCLUDES)
LDFLAGS :=
ifneq ($(strip $(DRAMSIM3_ROOT)),)
CXXFLAGS += -DSPINE_HAVE_DIRECT_DRAMSIM3 -I$(DRAMSIM3_ROOT)/src
LDFLAGS += -L$(DRAMSIM3_ROOT) -Wl,-rpath,$(DRAMSIM3_ROOT) -ldramsim3
endif
SOURCES := online_memory_probe.cpp \
           direct_dramsim3_engine.cpp \
           $(ROOT)/cpp/src/algorithm.cpp \
           $(ROOT)/cpp/src/algorithm_pipeline.cpp \
           $(ROOT)/cpp/src/axi.cpp \
           $(ROOT)/cpp/src/grasu.cpp \
           $(ROOT)/cpp/src/grasu_native.cpp \
           $(ROOT)/cpp/src/grasu_regraph.cpp \
           $(ROOT)/cpp/src/grasu_regraph_runtime.cpp \
           $(ROOT)/cpp/src/grasu_sharded_update.cpp \
           $(ROOT)/cpp/src/memory_backend.cpp \
           $(ROOT)/cpp/src/scheduler.cpp \
           $(ROOT)/cpp/src/spine_dirty.cpp \
           $(ROOT)/cpp/src/spine_l0.cpp \
           $(ROOT)/cpp/src/spine_owner.cpp \
           $(ROOT)/cpp/src/spine_pagerank.cpp \
           $(ROOT)/cpp/src/spine_split.cpp \
           $(ROOT)/cpp/src/spine_system.cpp \
           $(ROOT)/cpp/src/spine_vertex_lifecycle.cpp
HEADERS := $(wildcard $(ROOT)/cpp/include/spine_sim/*.hpp)

.PHONY: all clean native pgo-generate pgo-use pgo-native-generate \
        pgo-native-use
all: $(TARGET)

native:
	$(MAKE) -B all NATIVE_HOST=1 BUILD_DIR="$(BUILD_DIR)"

pgo-generate:
	mkdir -p $(PGO_PROFILE_DIR)
	$(MAKE) -B all PGO_MODE=generate BUILD_DIR="$(BUILD_DIR)" PGO_PROFILE_DIR="$(PGO_PROFILE_DIR)"

pgo-use:
	@test -n "$$(find "$(PGO_PROFILE_DIR)" -type f -name '*.gcda' -print -quit 2>/dev/null)" || \
		{ echo "error: no PGO training data under $(PGO_PROFILE_DIR)" >&2; exit 2; }
	$(MAKE) -B all PGO_MODE=use BUILD_DIR="$(BUILD_DIR)" PGO_PROFILE_DIR="$(PGO_PROFILE_DIR)"

pgo-native-generate:
	$(MAKE) pgo-generate NATIVE_HOST=1 BUILD_DIR="$(BUILD_DIR)" \
		PGO_PROFILE_DIR="$(PGO_PROFILE_DIR)"

pgo-native-use:
	$(MAKE) pgo-use NATIVE_HOST=1 BUILD_DIR="$(BUILD_DIR)" \
		PGO_PROFILE_DIR="$(PGO_PROFILE_DIR)"

$(TARGET): $(SOURCES) $(HEADERS) Makefile
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(SOURCES) -shared -o $@ $(LDFLAGS)

clean:
	rm -f $(TARGET)
