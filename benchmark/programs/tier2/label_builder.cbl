      * LABEL BUILDER (tier 2): STRING and INSPECT
      * Record (15 bytes): PART X(8) | REGION X(3) | SERIAL 9(4)
      * Label = REGION-PART-SERIAL, each text part cut at its first
      * space. Then every "0" in the label becomes "O", and the "A"s
      * in PART are counted. STRING does not clear its target, so the
      * label is blanked first.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LBLBUILD.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PART-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  PART-FILE.
       01  PART-REC.
           05 LB-PART        PIC X(8).
           05 LB-REGION      PIC X(3).
           05 LB-SERIAL      PIC 9(4).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-LABEL          PIC X(20)    VALUE SPACES.
       01  WS-A-COUNT        PIC 99       VALUE 0.
       01  WS-TOTAL-A        PIC 999      VALUE 0.
       01  WS-COUNT          PIC 999      VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT PART-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE PART-FILE
           PERFORM SUMMARY-PARA
           STOP RUN.

       READ-PARA.
           READ PART-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           MOVE SPACES TO WS-LABEL
           MOVE 0 TO WS-A-COUNT
           INSPECT LB-PART TALLYING WS-A-COUNT FOR ALL "A"
           STRING LB-REGION DELIMITED BY SPACE
                  "-" DELIMITED BY SIZE
                  LB-PART DELIMITED BY SPACE
                  "-" DELIMITED BY SIZE
                  LB-SERIAL DELIMITED BY SIZE
               INTO WS-LABEL
           END-STRING
           INSPECT WS-LABEL REPLACING ALL "0" BY "O"
           ADD WS-A-COUNT TO WS-TOTAL-A
           ADD 1 TO WS-COUNT
           DISPLAY WS-LABEL " A=" WS-A-COUNT
           PERFORM READ-PARA.

       SUMMARY-PARA.
           DISPLAY "LABELS: " WS-COUNT " A-TOTAL: " WS-TOTAL-A.