CXX ?= g++
SST_BIN ?= /data/feiyang/sst/bin
SST_CONFIG := $(SST_BIN)/sst-config
SST_CXXFLAGS := $(shell $(SST_CONFIG) --ELEMENT_CXXFLAGS)

ROOT := ../..
BUILD_DIR ?= $(ROOT)/build/sst
TARGET := $(BUILD_DIR)/libspine_cycle.so
INCLUDES := -I$(ROOT)/cpp/include
CXXFLAGS := $(SST_CXXFLAGS) -std=c++20 -O2 -g -fPIC -Wall -Wextra \
            -Wpedantic $(INCLUDES)
SOURCES := online_memory_probe.cpp \
           $(ROOT)/cpp/src/algorithm.cpp \
           $(ROOT)/cpp/src/algorithm_pipeline.cpp \
           $(ROOT)/cpp/src/axi.cpp \
           $(ROOT)/cpp/src/grasu.cpp \
           $(ROOT)/cpp/src/grasu_native.cpp \
           $(ROOT)/cpp/src/grasu_regraph.cpp \
           $(ROOT)/cpp/src/memory_backend.cpp \
           $(ROOT)/cpp/src/scheduler.cpp \
           $(ROOT)/cpp/src/spine_dirty.cpp \
           $(ROOT)/cpp/src/spine_l0.cpp \
           $(ROOT)/cpp/src/spine_pagerank.cpp \
           $(ROOT)/cpp/src/spine_split.cpp \
           $(ROOT)/cpp/src/spine_system.cpp
HEADERS := $(wildcard $(ROOT)/cpp/include/spine_sim/*.hpp)

.PHONY: all clean
all: $(TARGET)

$(TARGET): $(SOURCES) $(HEADERS) Makefile
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(SOURCES) -shared -o $@

clean:
	rm -f $(TARGET)
